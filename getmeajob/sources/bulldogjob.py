"""Bulldogjob public English sitemap and job pages."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .public_sitemap import PublicSitemapSource
from .rocketjobs import _text

BASE_URL = "https://bulldogjob.com"
JOB_PATH = re.compile(r"/companies/jobs/\d+-[^/]+/?$")


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"bulldogjob.pl", "bulldogjob.com"} or not JOB_PATH.fullmatch(parsed.path):
        raise ValueError("Bulldogjob: podaj bezpośredni link do oferty")
    return BASE_URL + parsed.path.rstrip("/")


def _salary(data: Any, basis: str) -> dict[str, Any] | None:
    if not isinstance(data, dict) or data.get("hidden"):
        return None
    amounts = [int(value.replace(" ", "")) for value in re.findall(r"\d[\d\s]*\d|\d+", str(data.get("money") or ""))]
    if len(amounts) < 2:
        return None
    period = str(data.get("timeframe") or "").lower()
    return {
        "minimum": amounts[0], "maximum": amounts[1],
        "currency": data.get("currency"),
        "unit": "month" if period in {"month", "monthly"} else "hour" if period in {"hour", "hourly"} else period or None,
        "basis": basis,
    }


def parse_job_page(url: str, page: str) -> dict[str, Any]:
    soup = BeautifulSoup(page, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        raise ValueError("Bulldogjob: brak danych oferty")
    try:
        job = json.loads(script.string or script.get_text())["props"]["pageProps"]["data"]["job"]
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Bulldogjob: nieprawidłowe dane oferty") from exc
    if not isinstance(job, dict) or job.get("state") != "published":
        raise ValueError("Bulldogjob: oferta nie jest aktywna")
    contracts = []
    salaries = []
    for flag, label, field, basis in (
        ("contractB2b", "B2B", "b2bSalary", "b2b_net"),
        ("contractEmployment", "UoP", "employmentSalary", "uop_gross"),
    ):
        if job.get(flag):
            contracts.append(label)
            value = _salary(job.get(field), basis)
            if value:
                salaries.append((label, value))
    if job.get("contractOther"):
        contracts.append("Inna")
    modes = set(job.get("workModes") or [])
    if job.get("remote") is True:
        remote_mode = "remote"
    elif "hybrid" in modes:
        remote_mode = "hybrid"
    elif "on-site" in modes or "onsite" in modes:
        remote_mode = "onsite"
    elif "remote" in modes:
        remote_mode = "remote"
    else:
        remote_mode = "unknown"
    description = "\n".join(_text(job.get(key)) for key in ("details", "requirements", "offer") if job.get(key))
    if remote_mode != "unknown":
        description = f"Work model: {remote_mode}. " + description
    if salaries:
        description += "\n" + "\n".join(
            f"Salary {label}: {value['minimum']}–{value['maximum']} {value['currency']} / {value['unit']}."
            for label, value in salaries
        )
    salary = salaries[0][1] if len(salaries) == 1 and len(contracts) == 1 else {
        "minimum": None, "maximum": None, "currency": None, "unit": None, "basis": "unknown",
    }
    locations = []
    for item in job.get("locations") or []:
        location = item.get("location") or {}
        city = location.get("cityPl") or location.get("cityEn")
        if city:
            locations.append(city)
    if job.get("remote") and not locations:
        locations.append("Remote")
    return {
        "source": "bulldogjob", "url": canonical_url(url),
        "title": _text(job.get("position")),
        "company": _text((job.get("company") or {}).get("name")),
        "description": description, "location": ", ".join(dict.fromkeys(locations)),
        "remote_mode": remote_mode, "contract_types": contracts, "salary": salary,
        "posted_at": job.get("publishedAt"), "expires_at": job.get("endsAt"),
        "source_updated_at": None,
    }


class BulldogjobSource(PublicSitemapSource):
    source_id = "bulldogjob"
    display_name = "Bulldogjob"
    base_url = BASE_URL
    sitemap_url = BASE_URL + "/en/jobs.xml.gz"
    job_prefix = "/companies/jobs/"
    parse_job_page = staticmethod(parse_job_page)

    def _job_url(self, url: str) -> bool:
        return super()._job_url(url) and bool(JOB_PATH.fullmatch(urlparse(url).path))

    def fetch_offer(self, url: str) -> dict[str, Any]:
        return super().fetch_offer(canonical_url(url))
