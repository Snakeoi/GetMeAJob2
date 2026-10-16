"""Read public NFJ HTML and its embedded state; never call the private API."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from ..search_profile import role_parts, slug_matches_roles
from .rocketjobs import _text

BASE_URL = "https://nofluffjobs.com"
USER_AGENT = "GetMeAJob/0.1 (personal job search; public HTML reader)"
JOB_PATH = re.compile(r"/(?:pl/)?job/[^/]+/?$")


def _state(page: str) -> dict[str, Any]:
    script = BeautifulSoup(page, "html.parser").find("script", id="serverApp-state")
    try:
        state = json.loads(script.get_text() if script else "null")
    except (ValueError, TypeError) as exc:
        raise ValueError("No Fluff Jobs: nieprawidłowe dane strony") from exc
    if not isinstance(state, dict):
        raise ValueError("No Fluff Jobs: brak danych strony (serverApp-state)")
    return state


def _date(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    return value if isinstance(value, str) else None


def parse_job_page(url: str, page: str) -> dict[str, Any]:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    data = next((value for key, value in _state(page).items()
                 if key.split("?", 1)[0] == f"/posting/{slug}" and isinstance(value, dict)), None)
    if not data or not data.get("title"):
        raise ValueError("No Fluff Jobs: brak danych konkretnej oferty")
    if data.get("status") != "PUBLISHED":
        raise ValueError("No Fluff Jobs: oferta nie jest aktywna")
    requirements = data.get("requirements") or {}
    specs = data.get("specs") or {}
    location = data.get("location") or {}
    descriptions = [
        _text((data.get("details") or {}).get("description")),
        "Wymagania: " + _text(requirements.get("description")),
        "Obowiązkowe: " + ", ".join(item.get("value", "") for item in requirements.get("musts", [])),
        "Mile widziane: " + ", ".join(item.get("value", "") for item in requirements.get("nices", [])),
        "Języki: " + ", ".join(" ".join(str(item.get(k) or "") for k in ("code", "level", "type"))
                                for item in requirements.get("languages", [])),
        "Obowiązki: " + _text("\n".join(specs.get("dailyTasks") or [])),
    ]
    # NFJ's public posting state: 5 = fully remote, 4 = hybrid.
    mode = {5: "remote", 4: "hybrid"}.get(location.get("remote"), "unknown")
    header = BeautifulSoup(page, "html.parser").get_text(" ", strip=True)
    header = re.split(r"Obowiązkowe|Must have|Opis wymagań|Requirements description", header, maxsplit=1)[0]
    if location.get("hybridDesc") or re.search(r"hybryd|hybrid", header, re.I):
        mode = "hybrid"
    elif re.search(r"stacjonarn|on.site|in.office", header, re.I):
        mode = "onsite"
    if mode != "unknown":
        descriptions.append(f"Work model: {mode}. {location.get('hybridDesc') or ''}")
    salary_data = (data.get("essentials") or {}).get("originalSalary") or {}
    types = salary_data.get("types") or {}
    if not isinstance(types, dict):
        types = {}
    contract_map = {"b2b": "B2B", "permanent": "UoP", "uop": "UoP"}
    contracts = list(dict.fromkeys(contract_map.get(key, key) for key in types))
    salaries = []
    for kind, values in types.items():
        if not isinstance(values, dict):
            # NFJ also uses flags such as {"intern": true} for offers
            # without a salary range. Keep the contract for filtering.
            continue
        bounds = values.get("range") or []
        salary = {
            "minimum": bounds[0] if len(bounds) == 2 else None,
            "maximum": bounds[1] if len(bounds) == 2 else None,
            "currency": salary_data.get("currency"),
            "unit": str(values.get("period") or "").lower() or None,
            "basis": {"b2b": "b2b_net", "permanent": "uop_gross", "uop": "uop_gross"}.get(kind, "unknown"),
        }
        salaries.append(salary)
        descriptions.append(f"Wynagrodzenie ({contract_map.get(kind, kind)}): "
                            f"{salary['minimum']}–{salary['maximum']} {salary['currency']} / {salary['unit']}; {salary['basis']}.")
    # The common model holds one salary. Do not combine ranges for different contracts.
    salary = salaries[0] if len(salaries) == 1 else {
        "minimum": None, "maximum": None, "currency": None, "unit": None, "basis": "unknown",
    }
    return {
        "source": "nofluffjobs", "url": url, "title": _text(data["title"]),
        "company": _text((data.get("company") or {}).get("name")),
        "description": "\n".join(descriptions),
        "location": ", ".join(dict.fromkeys(place["city"] for place in location.get("places", []) if place.get("city"))),
        "remote_mode": mode, "contract_types": contracts, "salary": salary,
        "posted_at": _date(data.get("posted")), "expires_at": _date(data.get("expiresAt")),
        "source_updated_at": _date(data.get("renewed")),
    }


class NoFluffJobsSource:
    source_id = "nofluffjobs"
    display_name = "No Fluff Jobs"

    def __init__(self, client: httpx.Client | None = None, delay_seconds: float = 0.5,
                 max_pages_per_term: int = 3, max_candidates_per_term: int = 60):
        self.client = client or httpx.Client(timeout=25, headers={"User-Agent": USER_AGENT})
        self.delay_seconds = delay_seconds
        self.max_pages_per_term = max_pages_per_term
        self.max_candidates_per_term = max_candidates_per_term
        self.robots: RobotFileParser | None = None

    def _get(self, url: str) -> str:
        # Validate each redirect before following it, including with injected clients.
        for _ in range(6):
            parsed = urlparse(url)
            if (parsed.scheme != "https" or parsed.netloc != "nofluffjobs.com"
                    or parsed.username or parsed.password):
                raise ValueError("No Fluff Jobs: niedozwolony adres lub przekierowanie")
            if self.robots is not None and not self.robots.can_fetch(USER_AGENT, url):
                raise ValueError("No Fluff Jobs: robots.txt nie zezwala na pobranie strony")
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            response = self.client.get(url, follow_redirects=False)
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            return response.text
        raise ValueError("No Fluff Jobs: zbyt wiele przekierowań")

    def _load_robots(self) -> None:
        self.robots = None
        rules = self._get(BASE_URL + "/robots.txt")
        self.robots = RobotFileParser()
        self.robots.parse(rules.splitlines())

    def fetch_offer(self, url: str) -> dict[str, Any]:
        if not JOB_PATH.fullmatch(urlparse(url).path):
            raise ValueError("No Fluff Jobs: podaj link do oferty")
        self._load_robots()
        return parse_job_page(url, self._get(url))

    def discover(self, profile: dict[str, Any], diagnostics: dict[str, Any]) -> list[str]:
        self._load_robots()
        found: dict[str, None] = {}
        terms = list(dict.fromkeys(role_parts(role)[0] for role in profile.get("roles", [])))
        diagnostics.update(pages_fetched=0, listing_entries=0, candidates=0, detail_errors=0,
                           max_pages_per_term=self.max_pages_per_term,
                           max_candidates_per_term=self.max_candidates_per_term)
        for term in terms:
            term_seen: set[str] = set()
            term_candidates: set[str] = set()
            for page in range(1, self.max_pages_per_term + 1):
                query = urlencode({"criteria": "keyword=" + term, "page": page})
                state = _state(self._get(BASE_URL + "/pl/?" + query))
                listing = next((value for value in state.values() if isinstance(value, dict)
                                and "criteriaSearch" in value and isinstance(value.get("postings"), list)), None)
                if listing is None:
                    raise ValueError("No Fluff Jobs: brak wyników wyszukiwania w danych strony")
                diagnostics["pages_fetched"] += 1
                new_entries = 0
                for posting in listing["postings"]:
                    slug = posting.get("url")
                    if not isinstance(slug, str) or not slug or "/" in slug or "?" in slug or "#" in slug:
                        continue
                    url = BASE_URL + "/pl/job/" + slug
                    if url in term_seen:
                        continue
                    term_seen.add(url)
                    new_entries += 1
                    diagnostics["listing_entries"] += 1
                    if not slug_matches_roles(posting.get("title") or slug, [term]):
                        continue
                    if self.robots.can_fetch(USER_AGENT, url):
                        term_candidates.add(url)
                        found[url] = None
                    if len(term_candidates) >= self.max_candidates_per_term:
                        break
                if (len(term_candidates) >= self.max_candidates_per_term or not new_entries
                        or page >= listing.get("totalPages", page)):
                    break
        diagnostics["candidates"] = len(found)
        return list(found)

    def offers(self, progress: Callable[[int, int], None] | None = None,
               profile: dict[str, Any] | None = None,
               diagnostics: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        diagnostics = diagnostics if diagnostics is not None else {}
        urls = self.discover(profile or {}, diagnostics)
        for index, url in enumerate(urls, 1):
            try:
                yield parse_job_page(url, self._get(url))
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                diagnostics["detail_errors"] += 1
                diagnostics.setdefault("errors", []).append({"url": url, "error": str(exc)})
            finally:
                if progress:
                    progress(index, len(urls))
