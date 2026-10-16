from __future__ import annotations

import html
import json
import re
import subprocess
import time
from typing import Any, Callable, Iterator
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .rocketjobs import TITLE_HINT, _text
from ..search_profile import search_terms, slug_matches_roles


BASE_URL = "https://www.pracuj.pl"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
READER_BASE = "https://r.jina.ai/http://www.pracuj.pl"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
SEARCH_TERMS = ("python developer", "backend python", "full stack vue")


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(("https", "www.pracuj.pl", unquote(parsed.path), "", ""))


def _markdown_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#]+", " ", text)
    return " ".join(text.split())


def _contracts(values: list[str] | str | None) -> list[str]:
    text = " ".join(values) if isinstance(values, list) else str(values or "")
    result = []
    if re.search(r"umow\w*\s+o\s+prac|permanent", text, re.I):
        result.append("UoP")
    if re.search(r"\bB2B\b", text, re.I):
        result.append("B2B")
    return result


def _remote_mode(values: list[str] | str | None) -> str:
    text = " ".join(values) if isinstance(values, list) else str(values or "")
    if re.search(r"hybryd|hybrid", text, re.I):
        return "hybrid"
    if re.search(r"stacjonarn|on[\s-]?site", text, re.I):
        return "onsite"
    if re.search(r"zdaln|remote", text, re.I):
        return "remote"
    return "unknown"


def _salary(text: str, contracts: list[str]) -> dict[str, Any]:
    normalized = re.sub(r"[\u00a0\u202f]", " ", text or "")
    amounts = [int(value.replace(" ", "")) for value in re.findall(r"\d[\d ]*\d|\d+", normalized)]
    result: dict[str, Any] = {
        "minimum": amounts[0] if amounts else None,
        "maximum": amounts[1] if len(amounts) > 1 else amounts[0] if amounts else None,
        "currency": "PLN" if re.search(r"zł|PLN", normalized, re.I) else None,
        "unit": "hour" if re.search(r"godz", normalized, re.I) else "month" if re.search(r"mies", normalized, re.I) else None,
        "basis": "unknown",
    }
    if re.search(r"netto", normalized, re.I) and "B2B" in contracts:
        result["basis"] = "b2b_net"
    elif re.search(r"brutto", normalized, re.I) and "UoP" in contracts:
        result["basis"] = "uop_gross"
    return result


def _search_data(page: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(page, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        return []
    data = json.loads(script.string or script.get_text())
    queries = (((data.get("props") or {}).get("pageProps") or {}).get("dehydratedState") or {}).get("queries") or []
    query = next((item for item in queries if (item.get("queryKey") or [None])[0] == "jobOffers"), None)
    return (((query or {}).get("state") or {}).get("data") or {}).get("groupedOffers") or []


def parse_search_page(page: str) -> list[dict[str, Any]]:
    groups = _search_data(page)
    if groups:
        results = []
        for group in groups:
            contracts = _contracts(group.get("typesOfContract"))
            for location in group.get("offers") or []:
                url = location.get("offerAbsoluteUri")
                if not url:
                    continue
                results.append({
                    "source": "pracuj",
                    "url": _canonical_url(url),
                    "title": _text(group.get("jobTitle")),
                    "company": _text(group.get("companyName")),
                    "description": _text(group.get("jobDescription")),
                    "location": _text(location.get("displayWorkplace")),
                    "remote_mode": _remote_mode(group.get("workModes")),
                    "contract_types": contracts,
                    "salary": _salary(str(group.get("salaryDisplayText") or ""), contracts),
                    "posted_at": group.get("initialPublicated"),
                    "expires_at": group.get("expirationDate"),
                    "source_updated_at": group.get("lastPublicated"),
                })
        return results
    return parse_reader_search(page)


def parse_reader_search(markdown: str) -> list[dict[str, Any]]:
    heading = re.compile(
        r"^## \[(?P<title>[^\]]+)\]\((?P<url>https://www\.pracuj\.pl/praca/[^ )]+)", re.M
    )
    matches = list(heading.finditer(markdown))
    results = []
    for index, match in enumerate(matches):
        block = markdown[match.start(): matches[index + 1].start() if index + 1 < len(matches) else len(markdown)]
        company_match = re.search(r"!\[Image \d+: ([^\]]+)\]", block)
        location_match = re.search(r"^####\s+(.+)$", block, re.M)
        salary_match = re.search(r"^([\d\s  ]+(?:[–-][\d\s  ]+)?\s*zł[^\n]*)$", block, re.M | re.I)
        contracts = _contracts(block)
        location = _markdown_text(location_match.group(1)) if location_match else ""
        if "Miejsce pracy:" in location:
            location = location.split("Miejsce pracy:", 1)[1].split("Siedziba firmy:", 1)[0].strip()
        results.append({
            "source": "pracuj",
            "url": _canonical_url(html.unescape(match.group("url"))),
            "title": html.unescape(match.group("title")),
            "company": html.unescape(company_match.group(1)) if company_match else "",
            "description": _markdown_text(block),
            "location": location,
            "remote_mode": _remote_mode(block),
            "contract_types": contracts,
            "salary": _salary(salary_match.group(1) if salary_match else "", contracts),
            "posted_at": None,
            "expires_at": None,
            "source_updated_at": None,
        })
    return results


def parse_job_page(
    url: str, page: str, listing_offer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(listing_offer or {})
    soup = BeautifulSoup(page, "html.parser")
    schema = None
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            candidate = json.loads(html.unescape(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
            schema = candidate
            break
    if not schema:
        if page.startswith("Title:") or "Markdown Content:" in page:
            if not base:
                raise ValueError("Tekstowy podgląd Pracuj.pl wymaga danych z listy ofert")
            base["description"] = _text(page.split("Markdown Content:", 1)[-1])
            return base
        raise ValueError("Pracuj.pl page has no JobPosting structured data")

    organization = schema.get("hiringOrganization") or ""
    if isinstance(organization, dict):
        organization = organization.get("name") or ""
    location = schema.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get("address") or {}
    description_parts = [
        schema.get("description"), schema.get("responsibilities"),
        schema.get("experienceRequirements"), schema.get("jobBenefits"),
    ]
    description = " ".join(_text(part) for part in description_parts if part)
    visible = soup.get_text(" ", strip=True)
    header = visible.split("Podobne oferty", 1)[0]
    contracts = _contracts(schema.get("employmentType")) or base.get("contract_types") or []
    remote_mode = base.get("remote_mode") or _remote_mode(header)
    return {
        "source": "pracuj",
        "url": _canonical_url(url),
        "title": _text(schema.get("title")) or base.get("title", ""),
        "company": _text(organization) or base.get("company", ""),
        "description": description or base.get("description", ""),
        "location": _text(address.get("addressLocality") or location.get("name")) or base.get("location", ""),
        "remote_mode": remote_mode,
        "contract_types": contracts,
        "salary": base.get("salary") or _salary(header, contracts),
        "posted_at": schema.get("datePosted") or base.get("posted_at"),
        "expires_at": schema.get("validThrough") or base.get("expires_at"),
        "source_updated_at": base.get("source_updated_at"),
    }


class PracujSource:
    source_id = "pracuj"
    display_name = "Pracuj.pl"

    def __init__(
        self, client: httpx.Client | None = None, delay_seconds: float = 0.5,
        max_pages: int = 6, max_candidates: int = 300,
        max_candidates_per_term: int = 100,
    ):
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=25,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8"},
        )
        self.delay_seconds = delay_seconds
        self.max_pages = max_pages
        self.max_candidates = max_candidates
        self.max_candidates_per_term = max_candidates_per_term

    def _direct_get(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        if response.url.host not in {"pracuj.pl", "www.pracuj.pl"}:
            raise ValueError("Unexpected redirect outside Pracuj.pl")
        return response.text

    def _get(self, url: str) -> str:
        try:
            page = self._direct_get(url)
            if "cf-mitigated" not in page and "Just a moment..." not in page:
                return page
        except httpx.HTTPError:
            pass
        parsed = urlsplit(url)
        reader_url = f"{READER_BASE}{parsed.path}"
        if parsed.query:
            reader_url += f"?{parsed.query}"
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/curl", "--fail", "--silent", "--show-error", "--location",
                    "--max-time", "30", reader_url,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=35,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Nie udało się uruchomić publicznego podglądu Pracuj.pl") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"Publiczny podgląd Pracuj.pl nie odpowiedział: {completed.stderr[-300:]}")
        return completed.stdout

    def _robots(self) -> RobotFileParser:
        parser = RobotFileParser()
        parser.parse(self._direct_get(ROBOTS_URL).splitlines())
        return parser

    def discover(self, diagnostics: dict[str, Any] | None = None, profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        stats = diagnostics if diagnostics is not None else {}
        terms = search_terms(profile["roles"]) if profile else list(SEARCH_TERMS)
        stats.update({
            "search_terms": terms, "pages_checked": 0,
            "listing_rows": 0, "title_filtered": 0, "duplicates": 0,
            "candidates": 0, "search_limit_reached": False,
            "candidates_by_term": {}, "term_limits_reached": [],
            "page_limits_reached": [], "max_pages_per_term": self.max_pages,
            "max_candidates_per_term": self.max_candidates_per_term,
            "max_candidates": self.max_candidates,
        })
        robots = self._robots()
        found: dict[str, dict[str, Any]] = {}
        for term in terms:
            term_urls: set[str] = set()
            term_candidates = 0
            page_limit_reached = False
            for page_number in range(1, self.max_pages + 1):
                suffix = f"?pn={page_number}" if page_number > 1 else ""
                url = f"{BASE_URL}/praca/{quote(term)};kw{suffix}"
                if not robots.can_fetch(USER_AGENT, url):
                    continue
                page_offers = parse_search_page(self._get(url))
                stats["pages_checked"] += 1
                if not page_offers:
                    break
                new_on_page = 0
                for offer in page_offers:
                    stats["listing_rows"] += 1
                    if offer["url"] not in term_urls:
                        term_urls.add(offer["url"])
                        new_on_page += 1
                    if not (slug_matches_roles(offer["title"], profile["roles"]) if profile else TITLE_HINT.search(offer["title"])):
                        stats["title_filtered"] += 1
                        continue
                    if offer["url"] in found:
                        stats["duplicates"] += 1
                        continue
                    found[offer["url"]] = offer
                    term_candidates += 1
                    stats["candidates"] = len(found)
                if len(found) >= self.max_candidates:
                    stats["search_limit_reached"] = True
                    stats["candidates_by_term"][term] = term_candidates
                    return list(found.values())
                    if term_candidates >= self.max_candidates_per_term:
                        break
                if not new_on_page or term_candidates >= self.max_candidates_per_term:
                    break
                if page_number == self.max_pages:
                    page_limit_reached = True
            stats["candidates_by_term"][term] = term_candidates
            if term_candidates >= self.max_candidates_per_term:
                stats["term_limits_reached"].append(term)
            if page_limit_reached:
                stats["page_limits_reached"].append(term)
        return list(found.values())

    def offers(
        self, progress: Callable[[int, int], None] | None = None,
        diagnostics: dict[str, Any] | None = None,
        profile: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        stats = diagnostics if diagnostics is not None else {}
        candidates = self.discover(stats, profile)
        stats.update({"details_ok": 0, "details_failed": 0, "detail_errors": {}})
        for index, candidate in enumerate(candidates, 1):
            try:
                offer = parse_job_page(candidate["url"], self._get(candidate["url"]), candidate)
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                stats["details_failed"] += 1
                reason = type(exc).__name__
                stats["detail_errors"][reason] = stats["detail_errors"].get(reason, 0) + 1
            else:
                stats["details_ok"] += 1
                yield offer
            if progress:
                progress(index, len(candidates))
            if self.delay_seconds:
                time.sleep(self.delay_seconds)

    def fetch_offer(self, url: str) -> dict[str, Any]:
        canonical = _canonical_url(url)
        page = self._get(canonical)
        try:
            return parse_job_page(canonical, page)
        except ValueError:
            listing = next((item for item in self.discover() if item["url"] == canonical), None)
            if not listing:
                raise ValueError("Nie znaleziono tej oferty w aktualnych wynikach Pracuj.pl")
            return parse_job_page(canonical, page, listing)
