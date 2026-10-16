from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .rocketjobs import _text, _xml_locations
from ..search_profile import slug_matches_roles


SITEMAP_URL = "https://justjoin.it/sitemaps/active-jobs.xml"
ROBOTS_URL = "https://justjoin.it/robots.txt"
USER_AGENT = "GetMeAJob/0.1 (personal job search; respectful sitemap reader)"
PYTHON_ROLE = re.compile(r"(?:python.*(?:developer|engineer|programista)|(?:developer|engineer|programista).*python)", re.I)
FULLSTACK_ROLE = re.compile(r"full-?stack", re.I)


def parse_job_page(url: str, page: str, source_updated_at: str | None = None) -> dict[str, Any]:
    soup = BeautifulSoup(page, "html.parser")
    posting = None
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(html.unescape(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            continue
        entries = parsed if isinstance(parsed, list) else [parsed]
        posting = next((entry for entry in entries if isinstance(entry, dict) and entry.get("@type") == "JobPosting"), None)
        if posting:
            break
    if not posting:
        raise ValueError("JustJoinIT page has no JobPosting structured data")

    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    visible = soup.get_text(" ", strip=True)
    header = re.split(r"Job description|Opis stanowiska", visible, maxsplit=1, flags=re.I)[0][:3500]
    contracts = []
    if re.search(r"\bB2B\b", header, re.I):
        contracts.append("B2B")
    if re.search(r"\bPermanent\b|\bUoP\b|Umowa o pracę", header, re.I):
        contracts.append("UoP")

    mode = str(posting.get("jobLocationType") or "").upper()
    work_schedule = re.search(r"\b\d+\s+onsite\s*/\s*\d+\s+remote\b", header, re.I)
    if re.search(r"\bHybrid\b|\bHybrydowo\b", header, re.I):
        remote_mode = "hybrid"
    elif re.search(r"\bOffice\b|\bStacjonarnie\b", header, re.I):
        remote_mode = "onsite"
    elif "TELECOMMUTE" in mode or re.search(r"\bRemote\b|\bZdalnie\b", header, re.I):
        remote_mode = "remote"
    else:
        remote_mode = "unknown"

    salary_data = posting.get("baseSalary") or {}
    salary_value = salary_data.get("value") or {}
    if isinstance(salary_value, (int, float)):
        salary_value = {"minValue": salary_value, "maxValue": salary_value}
    unit = str(salary_value.get("unitText") or "").upper()
    if re.search(r"Net per month\s*-\s*B2B|Netto miesięcznie\s*-\s*B2B", header, re.I):
        basis = "b2b_net"
    elif re.search(r"Gross per month\s*-\s*(?:Permanent|UoP)|Brutto miesięcznie\s*-\s*UoP", header, re.I):
        basis = "uop_gross"
    elif contracts == ["B2B"]:
        basis = "b2b_net_inferred"
    elif contracts == ["UoP"]:
        basis = "uop_gross_inferred"
    else:
        basis = "unknown"
    salary = {
        "minimum": salary_value.get("minValue"),
        "maximum": salary_value.get("maxValue"),
        "currency": salary_data.get("currency"),
        "unit": "month" if unit in {"MONTH", "MONTHLY"} else "hour" if unit in {"HOUR", "HOURLY"} else unit.lower() or None,
        "basis": basis,
    }
    organization = posting.get("hiringOrganization") or {}
    location = posting.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    description = _text(posting.get("description"))
    if remote_mode == "hybrid":
        detail = f", {work_schedule.group(0)}" if work_schedule else ""
        description = f"Work model: Hybrid{detail}. {description}"

    return {
        "source": "justjoin",
        "url": url,
        "title": _text(posting.get("title")),
        "company": _text(organization.get("name")),
        "description": description,
        "location": (location.get("address") or {}).get("addressLocality") or "",
        "remote_mode": remote_mode,
        "contract_types": contracts,
        "salary": salary,
        "posted_at": posting.get("datePosted"),
        "expires_at": posting.get("validThrough"),
        "source_updated_at": source_updated_at,
    }


class JustJoinSource:
    source_id = "justjoin"
    display_name = "JustJoinIT"

    def __init__(self, client: httpx.Client | None = None, delay_seconds: float = 0.5, max_candidates: int = 300):
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=20,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"},
        )
        self.delay_seconds = delay_seconds
        self.max_candidates = max_candidates

    def _get(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        if response.url.host not in {"justjoin.it", "public.justjoin.com"}:
            raise ValueError("Unexpected redirect outside JustJoinIT")
        return response.text

    def discover(self, profile: dict[str, Any] | None = None) -> list[tuple[str, str | None]]:
        robots = RobotFileParser()
        robots.parse(self._get(ROBOTS_URL).splitlines())
        pending = [SITEMAP_URL]
        found: list[tuple[str, str | None]] = []
        while pending:
            sitemap_url = pending.pop(0)
            kind, entries = _xml_locations(self._get(sitemap_url))
            if kind == "sitemapindex":
                pending.extend(url for url, _ in entries)
                continue
            if kind != "urlset":
                raise ValueError(f"Unknown sitemap format: {kind}")
            for url, lastmod in entries:
                parsed = urlparse(url)
                if parsed.netloc != "justjoin.it" or not parsed.path.startswith("/job-offer/"):
                    continue
                slug = parsed.path.rsplit("/", 1)[-1]
                if not (slug_matches_roles(slug, profile["roles"]) if profile else PYTHON_ROLE.search(slug) or FULLSTACK_ROLE.search(slug)):
                    continue
                if robots.can_fetch(USER_AGENT, url):
                    found.append((url, lastmod))
        found.sort(key=lambda item: item[1] or "", reverse=True)
        return found[: self.max_candidates]

    def offers(self, progress: Callable[[int, int], None] | None = None, profile: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        urls = self.discover(profile)
        for index, (url, lastmod) in enumerate(urls, 1):
            try:
                yield parse_job_page(url, self._get(url), lastmod)
            except (httpx.HTTPError, ValueError):
                continue
            finally:
                if progress:
                    progress(index, len(urls))
                if self.delay_seconds:
                    time.sleep(self.delay_seconds)
