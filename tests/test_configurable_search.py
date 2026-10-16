from urllib.parse import unquote

from getmeajob.api import create_app
from getmeajob.config import DEFAULT_CANDIDATE_PROFILE, DEFAULT_SEARCH_PROFILE
from getmeajob.search_profile import title_matches_roles
from getmeajob.sources.justjoin import JustJoinSource
from getmeajob.sources.pracuj import PracujSource
from getmeajob.sources.rocketjobs import RocketJobsSource, prefilter
from getmeajob.store import Store


def search_profile(**changes):
    return {
        **DEFAULT_SEARCH_PROFILE,
        "roles": ["Java Developer"],
        "work_modes": ["remote", "onsite"],
        "work_locations": ["Warszawa"],
        "contract_types": ["UoP"],
        "minimum_uop_gross_pln_month": 15000,
        **changes,
    }


def offer(**changes):
    return {
        "title": "Senior Java Engineer",
        "description": "Praca stacjonarna. Rozwój aplikacji Java.",
        "location": "Warszawa",
        "remote_mode": "onsite",
        "contract_types": ["UoP"],
        "salary": {"minimum": 16000, "maximum": 18000, "currency": "PLN", "unit": "month", "basis": "uop_gross"},
        **changes,
    }


def test_fresh_install_starts_without_personal_profile_and_requires_setup(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    assert store.get_setting("search_profile")["roles"] == []
    assert store.get_setting("candidate_profile") == DEFAULT_CANDIDATE_PROFILE == {"headline": "", "summary": "", "facts": []}
    client = create_app(storage_path=store.path).test_client()
    headers = {"X-Local-Token": client.get("/api/bootstrap").json["token"]}
    assert client.post("/api/sync", json={"sources": ["rocketjobs"]}, headers=headers).status_code == 400
    assert client.post("/api/evaluate", json={"ids": ["test"]}, headers=headers).status_code == 400
    assert client.put("/api/search-profile", json=search_profile(work_locations=[]), headers=headers).status_code == 400
    saved = client.put("/api/search-profile", json=search_profile(), headers=headers)
    assert saved.status_code == 200
    assert saved.json["roles"] == ["Java Developer"]
    assert client.put("/api/candidate-profile", json={"headline": "", "summary": "", "facts": []}, headers=headers).status_code == 200


def test_configured_roles_locations_contracts_and_salary_filter_offers():
    profile = search_profile()
    assert prefilter(offer(), profile)[0]
    assert not prefilter(offer(location="Kraków"), profile)[0]
    assert prefilter(offer(remote_mode="remote", description="W pełni zdalnie", location="Kraków"), profile)[0]
    assert not prefilter(offer(contract_types=["B2B"]), profile)[0]
    assert "15000" in prefilter(offer(salary={**offer()["salary"], "maximum": 14000}), profile)[1]
    assert not prefilter(offer(title="Senior Python Developer"), profile)[0]
    assert title_matches_roles("Senior Product Manager", "", ["Product Manager"])


def test_discovery_uses_saved_roles_instead_of_fixed_python_queries():
    profile = search_profile()

    class AllowAll:
        def can_fetch(self, *_):
            return True

    class Rocket(RocketJobsSource):
        def _robots(self):
            return AllowAll()

        def _get(self, _url):
            return ("<urlset><url><loc>https://rocketjobs.pl/oferta-pracy/senior-java-developer</loc></url>"
                    "<url><loc>https://rocketjobs.pl/oferta-pracy/senior-python-developer</loc></url></urlset>")

    class JustJoin(JustJoinSource):
        def _get(self, url):
            if url.endswith("robots.txt"):
                return "User-agent: *\nAllow: /"
            return ("<urlset><url><loc>https://justjoin.it/job-offer/senior-java-developer</loc></url>"
                    "<url><loc>https://justjoin.it/job-offer/senior-python-developer</loc></url></urlset>")

    class Pracuj(PracujSource):
        def __init__(self):
            super().__init__(delay_seconds=0, max_pages=1)
            self.urls = []

        def _robots(self):
            return AllowAll()

        def _get(self, url):
            self.urls.append(url)
            return "Brak ofert"

    rocket = Rocket(delay_seconds=0)
    justjoin = JustJoin(delay_seconds=0)
    pracuj = Pracuj()
    assert [url for url, _ in rocket.discover(profile)] == ["https://rocketjobs.pl/oferta-pracy/senior-java-developer"]
    assert [url for url, _ in justjoin.discover(profile)] == ["https://justjoin.it/job-offer/senior-java-developer"]
    assert pracuj.discover(profile=profile) == []
    assert len(pracuj.urls) == 1 and "java developer" in unquote(pracuj.urls[0])


def test_existing_profile_is_not_replaced_by_new_defaults(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    legacy = {"roles": ["Python Developer"], "remote_only": True, "contract_types": ["UoP"],
              "minimum_uop_gross_pln_month": 20000, "minimum_b2b_net_pln_month": 20000,
              "include_unknown_salary": True, "excluded_terms": []}
    store.set_setting("search_profile", legacy)
    assert Store(store.path).get_setting("search_profile") == legacy
    client = create_app(storage_path=store.path).test_client()
    headers = {"X-Local-Token": client.get("/api/bootstrap").json["token"]}
    updated = client.put("/api/search-profile", json={**legacy, "work_modes": ["remote", "onsite"],
        "work_locations": ["Bydgoszcz"]}, headers=headers)
    assert updated.status_code == 200
    assert Store(store.path).get_setting("search_profile")["work_locations"] == ["Bydgoszcz"]
