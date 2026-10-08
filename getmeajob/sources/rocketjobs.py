from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from ..remote import assess_remote_requirement


SITEMAP_URL = "https://rocketjobs.pl/sitemaps/active-jobs.xml"
ROBOTS_URL = "https://rocketjobs.pl/robots.txt"
USER_AGENT = "GetMeAJob/0.1 (personal job search; respectful sitemap reader)"
TITLE_HINT = re.compile(r"python|full-?stack|backend|software-engineer|vue", re.I)
FULLSTACK = re.compile(r"full[\s-]?stack", re.I)
DEVELOPER = re.compile(r"developer|programist|engineer|inżynier|inzynier", re.I)


def _xml_locations(xml_text: str) -> tuple[str, list[tuple[str, str | None]]]:
    root = ET.fromstring(xml_text.lstrip("\ufeff"))
    kind = root.tag.rsplit("}", 1)[-1]
    entries: list[tuple[str, str | None]] = []
    for child in root:
        loc = child.findtext("{*}loc")
        if loc:
            entries.append((loc.strip(), child.findtext("{*}lastmod")))
    return kind, entries


def _text(value: Any) -> str:
    return BeautifulSoup(html.unescape(str(value or "")), "html.parser").get_text(" ", strip=True)


def _salary(data: dict[str, Any], header: str, contracts: list[str]) -> dict[str, Any]:
    base = data.get("baseSalary") or {}
    value = base.get("value") or {}
    if isinstance(value, (int, float)):
        value = {"minValue": value, "maxValue": value}
    unit = str(value.get("unitText") or "").upper()
    result = {
        "minimum": value.get("minValue"),
        "maximum": value.get("maxValue"),
        "currency": base.get("currency") or None,
        "unit": "month" if unit in {"MONTH", "MONTHLY"} else "hour" if unit in {"HOUR", "HOURLY"} else unit.lower() or None,
        "basis": "unknown",
    }
    if result["minimum"] is None and result["maximum"] is None:
        return result
    if re.search(r"netto\s+miesięcznie\s*-\s*B2B", header, re.I):
        result["basis"] = "b2b_net"
    elif re.search(r"brutto\s+miesięcznie\s*-\s*UoP", header, re.I):
        result["basis"] = "uop_gross"
    elif contracts == ["B2B"]:
        result["basis"] = "b2b_net_inferred"
    elif contracts == ["UoP"]:
        result["basis"] = "uop_gross_inferred"
    return result


def parse_job_page(url: str, page: str, source_updated_at: str | None = None) -> dict[str, Any]:
    soup = BeautifulSoup(page, "html.parser")
    data: dict[str, Any] | None = None
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(html.unescape(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = parsed if isinstance(parsed, list) else [parsed]
        data = next((item for item in candidates if isinstance(item, dict) and item.get("@type") == "JobPosting"), None)
        if data:
            break
    if not data:
        raise ValueError("RocketJobs page has no JobPosting structured data")

    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    visible = soup.get_text(" ", strip=True)
    header = visible.split("Opis stanowiska", 1)[0][:3000]
    title = _text(data.get("title"))
    organization = data.get("hiringOrganization") or {}
    location_info = data.get("jobLocation") or {}
    if isinstance(location_info, list):
        location_info = location_info[0] if location_info else {}
    address = location_info.get("address") or {}
    location = address.get("addressLocality") or ""

    contracts = []
    if re.search(r"\bUoP\b|Umowa o pracę", header, re.I):
        contracts.append("UoP")
    if re.search(r"\bB2B\b", header, re.I):
        contracts.append("B2B")

    location_type = str(data.get("jobLocationType") or "").upper()
    if re.search(r"\bHybrydowo\b", header, re.I):
        remote_mode = "hybrid"
    elif re.search(r"\bStacjonarnie\b", header, re.I):
        remote_mode = "onsite"
    elif "TELECOMMUTE" in location_type or re.search(r"Praca w pełni zdalna|\bZdalnie\b", header, re.I):
        remote_mode = "remote"
    else:
        remote_mode = "unknown"

    return {
        "source": "rocketjobs",
        "url": url,
        "title": title,
        "company": _text(organization.get("name")),
        "description": _text(data.get("description")),
        "location": location,
        "remote_mode": remote_mode,
        "contract_types": contracts,
        "salary": _salary(data, header, contracts),
        "posted_at": data.get("datePosted"),
        "expires_at": data.get("validThrough"),
        "source_updated_at": source_updated_at,
    }


def prefilter(
    offer: dict[str, Any], profile: dict[str, Any], candidate: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    title = offer["title"]
    description = offer["description"]
    title_lower = title.lower()
    specialized_other_role = bool(re.search(r"\b(?:qa|quality assurance|test|testing|automation|slam|data engineer|devops)\b", title, re.I))
    python_role = "python" in title_lower and bool(DEVELOPER.search(title)) and not specialized_other_role
    python_backend = "backend" in title_lower and "python" in description.lower() and not specialized_other_role
    vue_fullstack = bool(FULLSTACK.search(title)) and bool(re.search(r"\bvue(?:\.js)?\b", description, re.I))
    role_matches = vue_fullstack if FULLSTACK.search(title) else python_role or python_backend
    if not role_matches:
        return False, "Stanowisko nie odpowiada Python Developer ani Full Stack z Vue"
    remote_ok, remote_reason = assess_remote_requirement(offer, profile, candidate)
    if not remote_ok:
        return False, remote_reason
    contracts = offer.get("contract_types") or []
    if contracts and not set(contracts).intersection(profile.get("contract_types", [])):
        return False, "Brak umowy UoP lub B2B"
    lowered = (title + " " + description).lower()
    for term in profile.get("excluded_terms", []):
        if term and term.lower() in lowered:
            return False, f"Wykluczona fraza: {term}"

    salary = offer.get("salary") or {}
    maximum = salary.get("maximum")
    if salary.get("currency") == "PLN" and salary.get("unit") == "month" and maximum is not None and len(contracts) == 1:
        basis = salary.get("basis", "")
        if basis.startswith("uop_") and maximum < profile["minimum_uop_gross_pln_month"]:
            return False, "Maksymalne wynagrodzenie UoP poniżej 20 000 PLN brutto/mies."
        if basis.startswith("b2b_") and maximum < profile["minimum_b2b_net_pln_month"]:
            return False, "Maksymalne wynagrodzenie B2B poniżej 20 000 PLN netto/mies."
    elif not profile.get("include_unknown_salary", True):
        return False, "Brak potwierdzonego wynagrodzenia miesięcznego"
    return True, ""


class RocketJobsSource:
    def __init__(self, client: httpx.Client | None = None, delay_seconds: float = 0.5):
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=20,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"},
        )
        self.delay_seconds = delay_seconds

    def _get(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        if response.url.host not in {"rocketjobs.pl", "public.justjoin.com"}:
            raise ValueError("Unexpected redirect outside RocketJobs")
        return response.text

    def _robots(self) -> RobotFileParser:
        parser = RobotFileParser()
        parser.parse(self._get(ROBOTS_URL).splitlines())
        return parser

    def discover(self) -> list[tuple[str, str | None]]:
        robots = self._robots()
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
                if parsed.netloc != "rocketjobs.pl" or not parsed.path.startswith("/oferta-pracy/"):
                    continue
                if not TITLE_HINT.search(parsed.path):
                    continue
                if robots.can_fetch(USER_AGENT, url):
                    found.append((url, lastmod))
        return found

    def offers(self, progress: Callable[[int, int], None] | None = None) -> Iterator[dict[str, Any]]:
        urls = self.discover()
        for index, (url, lastmod) in enumerate(urls, 1):
            try:
                yield parse_job_page(url, self._get(url), lastmod)
            except (httpx.HTTPError, ValueError):
                # Individual offers expire between sitemap publication and retrieval.
                continue
            finally:
                if progress:
                    progress(index, len(urls))
                if self.delay_seconds:
                    time.sleep(self.delay_seconds)
