import json
from urllib.parse import parse_qs, unquote, urlsplit

from tests.profile_fixtures import SAMPLE_CANDIDATE_PROFILE as DEFAULT_CANDIDATE_PROFILE, SAMPLE_SEARCH_PROFILE as DEFAULT_SEARCH_PROFILE
from getmeajob.sources.pracuj import PracujSource, SEARCH_TERMS, parse_job_page, parse_reader_search, parse_search_page
from getmeajob.sources.rocketjobs import prefilter


def search_page():
    offer = {
        "jobTitle": "Senior Python Developer",
        "companyName": "Example Tech",
        "initialPublicated": "2026-10-09T10:00:00Z",
        "lastPublicated": "2026-10-11T10:00:00Z",
        "expirationDate": "2026-11-09T22:59:59Z",
        "salaryDisplayText": "20 000–26 000 zł netto (+ VAT) / mies.",
        "jobDescription": "Python, Flask, REST i PostgreSQL.",
        "offers": [{
            "displayWorkplace": "Cała Polska (praca zdalna)",
            "offerAbsoluteUri": "https://www.pracuj.pl/praca/senior-python-developer,oferta,1000000001?ref=test",
        }],
        "typesOfContract": ["Kontrakt B2B"],
        "workModes": ["Praca zdalna"],
    }
    payload = {
        "props": {"pageProps": {"dehydratedState": {"queries": [{
            "queryKey": ["jobOffers", {}],
            "state": {"data": {"groupedOffers": [offer]}},
        }]}}},
    }
    return f"<html><script id='__NEXT_DATA__' type='application/json'>{json.dumps(payload)}</script></html>"


def detail_page():
    posting = {
        "@type": "JobPosting",
        "title": "Senior Python Developer",
        "hiringOrganization": "Example Tech",
        "employmentType": "kontrakt B2B",
        "datePosted": "2026-10-09T10:00:00Z",
        "validThrough": "2026-11-09T22:59:59Z",
        "jobLocation": {"address": {"addressLocality": "Warszawa"}},
        "responsibilities": "Rozwój REST API w Pythonie i Flask. Praca zdalna.",
        "experienceRequirements": "Minimum 5 lat doświadczenia w Pythonie.",
    }
    return (
        "<html><head><script id='job-schema-org' type='application/ld+json'>"
        + json.dumps(posting)
        + "</script></head><body>Praca zdalna</body></html>"
    )


def test_pracuj_next_data_and_job_schema_are_normalized():
    listing = parse_search_page(search_page())[0]
    assert listing["url"] == "https://www.pracuj.pl/praca/senior-python-developer,oferta,1000000001"
    assert listing["remote_mode"] == "remote"
    assert listing["contract_types"] == ["B2B"]
    assert listing["salary"] == {
        "minimum": 20000,
        "maximum": 26000,
        "currency": "PLN",
        "unit": "month",
        "basis": "b2b_net",
    }

    offer = parse_job_page(listing["url"], detail_page(), listing)
    assert offer["source"] == "pracuj"
    assert offer["company"] == "Example Tech"
    assert offer["location"] == "Warszawa"
    assert "Minimum 5 lat" in offer["description"]
    assert prefilter(offer, DEFAULT_SEARCH_PROFILE, DEFAULT_CANDIDATE_PROFILE) == (True, "")


def test_pracuj_canonical_url_removes_tracking_and_normalizes_encoded_commas():
    listing = parse_search_page(search_page().replace(
        ",oferta,1000000001?ref=test",
        "%2Coferta%2C1000000001?s=tracking",
    ))[0]
    assert listing["url"].endswith("senior-python-developer,oferta,1000000001")


def test_pracuj_hybrid_offer_is_rejected_even_when_python_matches():
    listing = parse_search_page(search_page())[0]
    listing["remote_mode"] = "hybrid"
    listing["description"] = "Python i Flask. Tryb hybrydowy, 1 dzień w biurze."
    assert not prefilter(listing, DEFAULT_SEARCH_PROFILE, DEFAULT_CANDIDATE_PROFILE)[0]


def test_pracuj_text_reader_fallback_extracts_public_listing():
    markdown = """
## [Python Developer](https://www.pracuj.pl/praca/python-developer-warszawa,oferta,1000000002?ref=test "Zobacz ofertę")

135 zł netto (+ VAT) / godz.

![Image 1: Example Company](https://example.invalid/logo.png)

#### Cała Polska (praca zdalna)

* Kontrakt B2B
* Praca zdalna

Twój zakres obowiązków: Python, Flask i REST API.
"""
    offer = parse_reader_search(markdown)[0]
    assert offer["company"] == "Example Company"
    assert offer["remote_mode"] == "remote"
    assert offer["contract_types"] == ["B2B"]
    assert offer["salary"]["minimum"] == 135
    assert offer["salary"]["unit"] == "hour"


def test_pracuj_text_reader_normalizes_whole_poland_location():
    markdown = """
## [Python Developer](https://www.pracuj.pl/praca/python-developer,oferta,1000000003)
![Image 1: Example](https://example.invalid/logo.png)
#### Miejsce pracy:**Cała Polska (praca zdalna)**Siedziba firmy:**Warszawa**
* Kontrakt B2B
* Praca zdalna
"""
    assert parse_reader_search(markdown)[0]["location"] == "Cała Polska (praca zdalna)"


def test_pracuj_search_checks_more_than_two_pages_and_each_phrase():
    class AllowAll:
        def can_fetch(self, *_args):
            return True

    class FakeSource(PracujSource):
        def _robots(self):
            return AllowAll()

        def _get(self, url):
            parsed = urlsplit(url)
            if ",oferta," in parsed.path:
                return "Title: offer\nMarkdown Content: Python, Vue, pełna praca zdalna."
            page = int(parse_qs(parsed.query).get("pn", [1])[0])
            if page > 3:
                return "Brak ofert"
            term = unquote(parsed.path.split("/praca/", 1)[1]).split(";kw", 1)[0]
            number = SEARCH_TERMS.index(term) * 10 + page
            return (
                f"## [Python Developer {number}](https://www.pracuj.pl/praca/python-developer-{number},oferta,{number:010d})\n"
                "#### Cała Polska (praca zdalna)\n* Kontrakt B2B\n* Praca zdalna\n"
            )

    source = FakeSource(delay_seconds=0, max_pages=6, max_candidates=300, max_candidates_per_term=100)
    diagnostics = {}
    offers = list(source.offers(diagnostics=diagnostics))

    assert len(offers) == 9
    assert diagnostics["pages_checked"] == 12
    assert diagnostics["candidates_by_term"] == {term: 3 for term in SEARCH_TERMS}
    assert diagnostics["details_ok"] == 9
    assert diagnostics["details_failed"] == 0

    limited = {}
    limited_offers = FakeSource(
        delay_seconds=0, max_pages=6, max_candidates=3, max_candidates_per_term=1,
    ).discover(limited)
    assert len(limited_offers) == 3
    assert limited["candidates_by_term"] == {term: 1 for term in SEARCH_TERMS}
    assert limited["search_limit_reached"]


def test_pracuj_detail_failure_is_counted_without_stopping_other_offers():
    class AllowAll:
        def can_fetch(self, *_args):
            return True

    class FakeSource(PracujSource):
        def _robots(self):
            return AllowAll()

        def _get(self, url):
            if ",oferta," in url:
                if ",oferta,0000000002" in url:
                    raise RuntimeError("Reader unavailable")
                return "Title: offer\nMarkdown Content: Python, praca zdalna."
            if "python%20developer" not in url or "?pn=" in url:
                return "Brak ofert"
            return (
                "## [Python Developer 1](https://www.pracuj.pl/praca/python-1,oferta,0000000001)\n"
                "#### Cała Polska (praca zdalna)\n* Kontrakt B2B\n* Praca zdalna\n"
                "## [Python Developer 2](https://www.pracuj.pl/praca/python-2,oferta,0000000002)\n"
                "#### Cała Polska (praca zdalna)\n* Kontrakt B2B\n* Praca zdalna\n"
            )

    diagnostics = {}
    offers = list(FakeSource(delay_seconds=0).offers(diagnostics=diagnostics))
    assert len(offers) == 1
    assert diagnostics["candidates"] == 2
    assert diagnostics["details_ok"] == 1
    assert diagnostics["details_failed"] == 1
    assert diagnostics["detail_errors"] == {"RuntimeError": 1}
