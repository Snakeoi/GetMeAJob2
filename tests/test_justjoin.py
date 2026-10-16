import json

from tests.profile_fixtures import SAMPLE_SEARCH_PROFILE as DEFAULT_SEARCH_PROFILE
from getmeajob.sources.justjoin import parse_job_page
from getmeajob.sources.rocketjobs import prefilter


def page(*, title="Senior Python Developer", description="Fully remote. Python, Flask and Vue", salary=23000, header="B2B Senior Remote"):
    posting = {
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "hiringOrganization": {"name": "Example"},
        "jobLocation": {"address": {"addressLocality": "Warszawa"}},
        "baseSalary": {"currency": "PLN", "value": {"unitText": "MONTH", "minValue": salary, "maxValue": salary + 2000}},
    }
    return (
        "<html><head><script type='application/ld+json'>" + json.dumps(posting)
        + "</script></head><body><h1>" + title + "</h1><div>"
        + header + "</div><div>" + str(salary) + " PLN Net per month - B2B</div>"
        + "<h2>Job description</h2><p>" + description + "</p></body></html>"
    )


def test_justjoin_python_offer_matches():
    offer = parse_job_page("https://justjoin.it/job-offer/example", page())
    assert offer["source"] == "justjoin"
    assert offer["remote_mode"] == "remote"
    assert offer["contract_types"] == ["B2B"]
    assert offer["salary"]["basis"] == "b2b_net"
    assert prefilter(offer, DEFAULT_SEARCH_PROFILE) == (True, "")


def test_justjoin_hybrid_offer_is_rejected():
    offer = parse_job_page("https://justjoin.it/job-offer/example", page(header="B2B Senior Hybrid 1 onsite / 4 remote"))
    assert offer["remote_mode"] == "hybrid"
    assert offer["description"].startswith("Work model: Hybrid, 1 onsite / 4 remote.")
    matches, reason = prefilter(offer, DEFAULT_SEARCH_PROFILE)
    assert not matches
    assert "1 dzień onsite / 4 dni zdalnie" in reason


def test_justjoin_fullstack_requires_vue():
    offer = parse_job_page("https://justjoin.it/job-offer/example", page(title="Fullstack Developer", description="React and Node.js"))
    assert not prefilter(offer, DEFAULT_SEARCH_PROFILE)[0]
