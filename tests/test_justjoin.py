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


def test_batches_persist_across_service_restart_and_include_filtered_offers(tmp_path):
    from getmeajob.sources.justjoin import JustJoinSource
    from getmeajob.service import JobService
    from getmeajob.store import Store

    urls = [f"https://justjoin.it/job-offer/python-developer-{i}" for i in range(5)]
    fetched = []

    class Source(JustJoinSource):
        def discover(self, profile=None):
            return [(url, None) for url in urls]

        def _get(self, url):
            fetched.append(url)
            return page(salary=1000)  # Filtered offers must also advance the cursor.

    store = Store(tmp_path / "db.sqlite3")
    store.set_setting("search_profile", DEFAULT_SEARCH_PROFILE)

    def sync(report=lambda *args: None):
        service = JobService(Store(tmp_path / "db.sqlite3"), source=Source(delay_seconds=0, max_candidates=2))
        return service.sync(report)["sources"][0]["discovery"]

    import pytest

    def interrupt_after_first_batch(message, current=None, total=None):
        if current == 2:
            assert total == 5
            raise RuntimeError("Simulated shutdown")

    with pytest.raises(RuntimeError, match="Simulated shutdown"):
        sync(interrupt_after_first_batch)
    urls.reverse()  # A positional offset would skip or repeat offers here.
    last = sync()
    assert last["remaining"] == 0
    assert last["checked"] == 3
    assert last["cycle_checked"] == 5
    assert len(fetched) == len(set(fetched)) == 5

    # One click refreshes all 5 offers, crossing both batch boundaries.
    progress = []
    last = sync(lambda message, current=None, total=None: progress.append((current, total)))
    assert last["remaining"] == 0
    assert last["checked"] == 5
    assert fetched[5:] == urls
    assert progress[1:] == [(i, 5) for i in range(1, 6)]


def test_errors_new_urls_profile_changes_and_interrupted_consumer():
    from getmeajob.sources.justjoin import JustJoinSource

    state = {}
    urls = ["bad", "good", "older"]

    class Source(JustJoinSource):
        def discover(self, profile=None):
            return [(url, None) for url in urls]

        def _get(self, url):
            if url == "bad":
                raise ValueError("No structured data")
            return page()

    source = Source(delay_seconds=0, max_candidates=2)
    diagnostics = {}
    list(source.offers(profile={"roles": ["Python"]}, diagnostics=diagnostics,
                       checkpoint=state, save_checkpoint=state.update))
    assert diagnostics["detail_errors"] == 1
    assert diagnostics["remaining"] == 0
    urls.insert(0, "new")
    offers = list(source.offers(profile={"roles": ["Python"]}, checkpoint=state, save_checkpoint=state.update))
    assert [offer["url"] for offer in offers] == ["new"]
    # A new profile resets the cycle, including previously failed details.
    diagnostics = {}
    list(source.offers(profile={"roles": ["Java"]}, checkpoint=state,
                       save_checkpoint=state.update, diagnostics=diagnostics))
    assert diagnostics["detail_errors"] == 1
    assert diagnostics["cycle_checked"] == 4

    previous = dict(state)
    iterator = source.offers(profile={"roles": ["Java"]}, checkpoint=state, save_checkpoint=state.update)
    next(iterator)
    iterator.close()  # Consumer failed before storing the yielded offer.
    assert state == previous


def test_discover_reads_all_submaps_and_deduplicates_before_batching():
    from getmeajob.sources.justjoin import JustJoinSource, ROBOTS_URL, SITEMAP_URL

    class Source(JustJoinSource):
        def _get(self, url):
            if url == ROBOTS_URL:
                return "User-agent: *\nAllow: /"
            if url == SITEMAP_URL:
                return "<sitemapindex><sitemap><loc>child</loc></sitemap><sitemap><loc>child</loc></sitemap></sitemapindex>"
            return "<urlset>" + "".join(
                f"<url><loc>https://justjoin.it/job-offer/python-developer-{i}</loc></url>"
                for i in [1, 2, 2, 3]
            ) + "</urlset>"

    assert len(Source(max_candidates=2).discover()) == 3
