import json

from tests.profile_fixtures import SAMPLE_CANDIDATE_PROFILE as DEFAULT_CANDIDATE_PROFILE, SAMPLE_SEARCH_PROFILE as DEFAULT_SEARCH_PROFILE
from getmeajob.sources.rocketjobs import _xml_locations, parse_job_page, prefilter


def page(title="Senior Python Developer", description="100% praca zdalna. Flask Vue SQL", salary=22000, header="UoP Zdalnie"):
    posting = {
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "hiringOrganization": {"name": "Acme"},
        "jobLocation": {"address": {"addressLocality": "Warszawa"}},
        "baseSalary": {
            "currency": "PLN",
            "value": {"unitText": "MONTH", "minValue": salary, "maxValue": salary + 3000},
        } if salary is not None else None,
    }
    return (
        "<html><head><script type='application/ld+json'>"
        + json.dumps(posting)
        + "</script></head><body><h1>"
        + title
        + "</h1><div>"
        + header
        + "</div><h2>Opis stanowiska</h2><p>"
        + description
        + "</p><div>Podobne oferty: 60 000 PLN/mies.</div></body></html>"
    )


def test_sitemap_index_and_offer_list():
    kind, rows = _xml_locations("<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><sitemap><loc>https://example.com/part.xml</loc></sitemap></sitemapindex>")
    assert kind == "sitemapindex"
    assert rows == [("https://example.com/part.xml", None)]
    kind, rows = _xml_locations("<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>https://example.com/job</loc><lastmod>2026-10-07</lastmod></url></urlset>")
    assert kind == "urlset"
    assert rows == [("https://example.com/job", "2026-10-07")]


def test_remote_python_offer_matches_profile():
    offer = parse_job_page("https://rocketjobs.pl/oferta-pracy/test", page())
    assert offer["title"] == "Senior Python Developer"
    assert offer["remote_mode"] == "remote"
    assert offer["contract_types"] == ["UoP"]
    assert offer["salary"]["minimum"] == 22000
    assert prefilter(offer, DEFAULT_SEARCH_PROFILE) == (True, "")


def test_on_site_or_underpaid_offer_is_rejected():
    onsite = parse_job_page("https://rocketjobs.pl/oferta-pracy/test", page(header="UoP Stacjonarnie"))
    assert not prefilter(onsite, DEFAULT_SEARCH_PROFILE)[0]
    underpaid = parse_job_page("https://rocketjobs.pl/oferta-pracy/test", page(salary=12000))
    assert "poniżej" in prefilter(underpaid, DEFAULT_SEARCH_PROFILE)[1]


def test_remote_label_is_rejected_when_description_requires_hybrid_work():
    offer = parse_job_page(
        "https://rocketjobs.pl/oferta-pracy/test",
        page(description="100% remote label. Hybrid by design with two days per week in the office."),
    )
    matches, reason = prefilter(offer, DEFAULT_SEARCH_PROFILE)
    assert not matches
    assert "hybrydowy" in reason


def test_remote_label_without_contradiction_in_description_is_accepted():
    offer = parse_job_page(
        "https://rocketjobs.pl/oferta-pracy/test",
        page(description="Flask Vue SQL", header="UoP Zdalnie"),
    )
    assert prefilter(offer, DEFAULT_SEARCH_PROFILE) == (True, "")


def test_any_work_mode_is_accepted_in_location_confirmed_by_cv():
    offer = parse_job_page(
        "https://rocketjobs.pl/oferta-pracy/test",
        page(description="Praca stacjonarna. Flask Vue SQL", header="UoP Stacjonarnie"),
    )
    offer["location"] = "Bydgoszcz"
    assert prefilter(offer, DEFAULT_SEARCH_PROFILE, DEFAULT_CANDIDATE_PROFILE) == (True, "")


def test_local_exception_requires_location_fact_from_cv():
    offer = parse_job_page(
        "https://rocketjobs.pl/oferta-pracy/test",
        page(description="Praca hybrydowa. Flask Vue SQL", header="UoP Hybrydowo"),
    )
    offer["location"] = "Bydgoszcz"
    candidate_without_location = {"facts": []}
    assert not prefilter(offer, DEFAULT_SEARCH_PROFILE, candidate_without_location)[0]


def test_similar_offers_do_not_supply_missing_salary():
    offer = parse_job_page("https://rocketjobs.pl/oferta-pracy/test", page(salary=None))
    assert offer["salary"]["minimum"] is None
    assert offer["salary"]["maximum"] is None


def test_fullstack_needs_vue_in_description():
    vue = parse_job_page("https://rocketjobs.pl/oferta-pracy/test", page(title="Full Stack Developer", description="Fully remote. Vue.js and REST"))
    react = parse_job_page("https://rocketjobs.pl/oferta-pracy/test", page(title="Full Stack Developer", description="Fully remote. React and REST"))
    assert prefilter(vue, DEFAULT_SEARCH_PROFILE)[0]
    assert not prefilter(react, DEFAULT_SEARCH_PROFILE)[0]


def test_python_qa_and_fullstack_react_are_not_target_roles():
    qa = parse_job_page("https://rocketjobs.pl/oferta-pracy/qa", page(title="QA Automation Engineer Python"))
    react = parse_job_page("https://rocketjobs.pl/oferta-pracy/react", page(title="Full Stack Engineer - Python React", description="Python and React"))
    assert not prefilter(qa, DEFAULT_SEARCH_PROFILE)[0]
    assert not prefilter(react, DEFAULT_SEARCH_PROFILE)[0]
