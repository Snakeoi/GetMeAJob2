"""SOLID.Jobs public offer sitemap and JobPosting pages."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .public_sitemap import PublicSitemapSource
from .rocketjobs import _text

BASE_URL = "https://solid.jobs"
JOB_PATH = re.compile(r"/offer/\d+/[^/]+/?$")


def parse_job_page(url: str, page: str) -> dict[str, Any]:
    soup = BeautifulSoup(page, "html.parser")
    posting = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            posting = data
            break
    if not posting or not posting.get("title"):
        raise ValueError("SOLID.Jobs: brak danych JobPosting")
    organization = posting.get("hiringOrganization") or {}
    location = posting.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get("address") or {}
    description = _text(posting.get("description"))
    visible = soup.get_text(" ", strip=True)
    header = visible.split("Zakres zadań", 1)[0].split("Job description", 1)[0][:2500]
    employment = str(posting.get("employmentType") or "").upper()
    contracts = []
    if employment == "CONTRACTOR" or re.search(r"\bB2B\b", header, re.I):
        contracts.append("B2B")
    if employment in {"FULL_TIME", "PERMANENT"} or re.search(r"\bUoP\b|umowa o pracę", header, re.I):
        contracts.append("UoP")
    if re.search(r"hybryd|hybrid", header, re.I):
        remote_mode = "hybrid"
    elif re.search(r"stacjonarn|on.site", header, re.I):
        remote_mode = "onsite"
    elif posting.get("jobLocationType") == "TELECOMMUTE" or re.search(r"100% zdalnie|fully remote", header, re.I):
        remote_mode = "remote"
    else:
        remote_mode = "unknown"
    salary_data = posting.get("baseSalary") or {}
    value = salary_data.get("value") or {}
    if isinstance(value, (float, int)):
        value = {"minValue": value, "maxValue": value}
    unit = str(value.get("unitText") or "").upper()
    salary = {
        "minimum": value.get("minValue"), "maximum": value.get("maxValue"),
        "currency": salary_data.get("currency"),
        "unit": "month" if unit in {"MONTH", "MONTHLY"} else "hour" if unit in {"HOUR", "HOURLY"} else unit.lower() or None,
        "basis": "b2b_net" if contracts == ["B2B"] else "uop_gross" if contracts == ["UoP"] else "unknown",
    }
    if remote_mode != "unknown":
        description = f"Work model: {remote_mode}. " + description
    return {
        "source": "solidjobs", "url": url,
        "title": _text(posting["title"]), "company": _text(organization.get("name")),
        "description": description,
        "location": _text(address.get("addressLocality") or location.get("name")),
        "remote_mode": remote_mode, "contract_types": contracts, "salary": salary,
        "posted_at": posting.get("datePosted"), "expires_at": posting.get("validThrough"),
        "source_updated_at": posting.get("dateModified"),
    }


class SolidJobsSource(PublicSitemapSource):
    source_id = "solidjobs"
    display_name = "SOLID.Jobs"
    base_url = BASE_URL
    sitemap_url = BASE_URL + "/sitemap-offers.xml"
    job_prefix = "/offer/"
    parse_job_page = staticmethod(parse_job_page)

    def _job_url(self, url: str) -> bool:
        return super()._job_url(url) and bool(JOB_PATH.fullmatch(urlparse(url).path))
