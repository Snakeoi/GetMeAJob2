"""Common, bounded reader for public job sitemaps and pages."""
from __future__ import annotations

import gzip
import time
from typing import Any, Callable, Iterator
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..search_profile import role_parts, title_matches_roles
from .rocketjobs import _xml_locations


class PublicSitemapSource:
    base_url: str
    sitemap_url: str
    job_prefix: str
    user_agent = "GetMeAJob/0.1 (personal job search; public sitemap reader)"

    def __init__(self, client: httpx.Client | None = None, delay_seconds: float = 0.5,
                 max_candidates: int = 150):
        self.client = client or httpx.Client(timeout=25, headers={"User-Agent": self.user_agent})
        self.delay_seconds = delay_seconds
        self.max_candidates = max_candidates
        self.robots: RobotFileParser | None = None

    def _get(self, url: str) -> bytes:
        domain = urlparse(self.base_url).netloc
        for _ in range(6):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.netloc != domain or parsed.username or parsed.password:
                raise ValueError(f"{self.display_name}: niedozwolony adres lub przekierowanie")
            if self.robots is not None and not self.robots.can_fetch(self.user_agent, url):
                raise ValueError(f"{self.display_name}: robots.txt zabrania pobrania strony")
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            response = self.client.get(url, follow_redirects=False)
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            if "Just a moment" in response.text[:300] or "cf-mitigated" in response.text[:300]:
                raise ValueError(f"{self.display_name}: strona wymaga weryfikacji przeglądarkowej")
            return response.content
        raise ValueError(f"{self.display_name}: zbyt wiele przekierowań")

    def _load_robots(self) -> None:
        self.robots = None
        content = self._get(self.base_url + "/robots.txt")
        robots = RobotFileParser()
        robots.parse(content.decode("utf-8-sig").splitlines())
        self.robots = robots

    def _job_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.netloc == urlparse(self.base_url).netloc
                and parsed.path.startswith(self.job_prefix)
                and not parsed.query and not parsed.fragment)

    def discover(self, profile: dict[str, Any], diagnostics: dict[str, Any]) -> list[tuple[str, str | None]]:
        self._load_robots()
        content = self._get(self.sitemap_url)
        if content.startswith(b"\x1f\x8b"):
            content = gzip.decompress(content)
        kind, entries = _xml_locations(content.decode("utf-8-sig"))
        if kind != "urlset":
            raise ValueError(f"{self.display_name}: nieoczekiwany format mapy ofert")
        diagnostics.update(sitemap_entries=len(entries), candidates=0, detail_errors=0,
                           max_candidates=self.max_candidates)
        matches: dict[str, str | None] = {}
        for url, updated in entries:
            slug = urlparse(url).path.rsplit("/", 1)[-1].replace("-", " ")
            positions = [role_parts(role)[0] for role in profile.get("roles", [])]
            if (self._job_url(url) and title_matches_roles(slug, "", positions)
                    and self.robots.can_fetch(self.user_agent, url)):
                matches[url] = updated
        selected = sorted(matches.items(), key=lambda item: item[1] or "", reverse=True)[:self.max_candidates]
        diagnostics["candidates"] = len(selected)
        return selected

    def fetch_offer(self, url: str) -> dict[str, Any]:
        if not self._job_url(url):
            raise ValueError(f"{self.display_name}: podaj bezpośredni link do oferty")
        self._load_robots()
        return self.parse_job_page(url, self._get(url).decode("utf-8-sig"))

    def offers(self, progress: Callable[[int, int], None] | None = None,
               profile: dict[str, Any] | None = None,
               diagnostics: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        diagnostics = diagnostics if diagnostics is not None else {}
        candidates = self.discover(profile or {}, diagnostics)
        for index, (url, updated) in enumerate(candidates, 1):
            try:
                offer = self.parse_job_page(url, self._get(url).decode("utf-8-sig"))
                offer["source_updated_at"] = updated or offer.get("source_updated_at")
                yield offer
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
                diagnostics["detail_errors"] += 1
                diagnostics.setdefault("errors", []).append({"url": url, "error": str(exc)})
            finally:
                if progress:
                    progress(index, len(candidates))
