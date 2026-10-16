import threading
import time

from getmeajob.api import create_app
from getmeajob.evaluation import normalize_result
from getmeajob.service import JobService
from getmeajob.store import Store
from tests.profile_fixtures import SAMPLE_CANDIDATE_PROFILE, SAMPLE_SEARCH_PROFILE


OFFER = {
    "source": "rocketjobs",
    "url": "https://rocketjobs.pl/oferta-pracy/example-python-developer",
    "title": "Python Developer",
    "company": "Example",
    "description": "Fully remote. Build Flask and Vue applications.",
    "location": "Warszawa",
    "remote_mode": "remote",
    "contract_types": ["UoP"],
    "salary": {"minimum": 22000, "maximum": 26000, "currency": "PLN", "unit": "month", "basis": "uop_gross"},
    "posted_at": "2026-10-07",
    "expires_at": "2026-11-07",
}


def evaluation():
    return {
        "recommendation": "aplikuj",
        "score": 89,
        "confidence": "wysoka",
        "rationale": "Doświadczenie w Flask i Vue odpowiada kluczowym zadaniom.",
        "requirements": ["Python", "Flask", "Vue.js", "Praca w pełni zdalna"],
        "matches": [{"requirement": "Flask", "candidate_fact_id": "nordea-backend", "explanation": "Rozwój aplikacji Flask."}],
        "gaps": [],
        "unknowns": [],
    }


def test_offer_versions_and_stale_evaluation(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    assert store.upsert_offer(OFFER) == "new"
    assert store.upsert_offer(OFFER) == "unchanged"
    offer_id = store.list_offers()[0]["id"]
    store.save_evaluation(offer_id, evaluation(), "test")
    assert not store.get_offer(offer_id)["evaluation_stale"]
    changed = {**OFFER, "description": "Build Flask, Vue and SQL applications."}
    assert store.upsert_offer(changed) == "changed"
    assert store.get_offer(offer_id)["evaluation_stale"]
    with store.connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM offer_snapshots WHERE offer_id = ?", (offer_id,)).fetchone()[0]
    assert count == 2


def test_approval_requires_evaluation_but_not_submission_note(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.upsert_offer(OFFER)
    offer_id = store.list_offers()[0]["id"]
    app = create_app(storage_path=store.path)
    client = app.test_client()
    token = client.get("/api/bootstrap").json["token"]
    assert client.post(f"/api/offers/{offer_id}/decision", json={"decision": "approved"}).status_code == 403
    headers = {"X-Local-Token": token}
    assert client.post(f"/api/offers/{offer_id}/decision", json={"decision": "approved"}, headers=headers).status_code == 400
    store.save_evaluation(offer_id, evaluation(), "test")
    assert client.post(f"/api/offers/{offer_id}/decision", json={"decision": "approved"}, headers=headers).status_code == 200
    assert client.post(f"/api/applications/{offer_id}/submitted", json={}, headers=headers).status_code == 200
    assert store.applications()[0]["confirmation"] == ""
    assert client.post(f"/api/applications/{offer_id}/submitted", json={"confirmation": "drugi raz"}, headers=headers).status_code == 400


def test_submission_note_is_saved_when_provided(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.upsert_offer(OFFER)
    offer_id = store.list_offers()[0]["id"]
    store.save_evaluation(offer_id, evaluation(), "test")
    app = create_app(storage_path=store.path)
    client = app.test_client()
    headers = {"X-Local-Token": client.get("/api/bootstrap").json["token"]}
    assert client.post(f"/api/offers/{offer_id}/decision", json={"decision": "approved"}, headers=headers).status_code == 200
    assert client.post(f"/api/applications/{offer_id}/submitted", json={"confirmation": "Dziękujemy za aplikację"}, headers=headers).status_code == 200
    assert store.applications()[0]["confirmation"] == "Dziękujemy za aplikację"


def test_undo_submission_restores_approved_application(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.upsert_offer(OFFER)
    offer_id = store.list_offers()[0]["id"]
    store.save_evaluation(offer_id, evaluation(), "test")
    store.set_decision(offer_id, "approved")
    original = store.applications()[0]
    client = create_app(storage_path=store.path).test_client()
    headers = {"X-Local-Token": client.get("/api/bootstrap").json["token"]}
    endpoint = f"/api/applications/{offer_id}/not-submitted"
    assert client.post(endpoint, headers=headers).status_code == 400
    store.mark_submitted(offer_id, "Potwierdzenie", "Notatka")
    assert client.post(endpoint).status_code == 403
    assert store.applications()[0]["status"] == "submitted"
    assert client.post(endpoint, headers=headers).status_code == 200
    restored = store.applications()[0]
    assert restored["id"] == original["id"]
    assert restored["approved_at"] == original["approved_at"]
    assert restored["status"] == "approved"
    assert restored["submitted_at"] is None
    assert restored["confirmation"] == restored["notes"] == ""
    assert store.get_offer(offer_id)["decision"] == "approved"
    assert client.post(endpoint, headers=headers).status_code == 400
    assert client.post("/api/applications/missing/not-submitted", headers=headers).status_code == 400
    assert client.post(f"/api/applications/{offer_id}/submitted", json={}, headers=headers).status_code == 200


def test_sync_uses_only_selected_sources(tmp_path):
    class FakeSource:
        def __init__(self, source_id, display_name):
            self.source_id = source_id
            self.display_name = display_name
            self.calls = 0

        def offers(self, progress=None):
            self.calls += 1
            return iter(())

    store = Store(tmp_path / "db.sqlite3")
    store.set_setting("search_profile", SAMPLE_SEARCH_PROFILE)
    sources = [FakeSource("rocketjobs", "RocketJobs"), FakeSource("justjoin", "JustJoinIT"), FakeSource("pracuj", "Pracuj.pl")]
    service = JobService(store, source=sources[0])
    service.sources = sources
    client = create_app(service=service).test_client()
    bootstrap = client.get("/api/bootstrap").json
    headers = {"X-Local-Token": bootstrap["token"]}
    assert bootstrap["sources"] == [
        {"id": "rocketjobs", "label": "RocketJobs"},
        {"id": "justjoin", "label": "JustJoinIT"},
        {"id": "pracuj", "label": "Pracuj.pl"},
    ]
    assert client.post("/api/sync", json={"sources": []}, headers=headers).status_code == 400
    assert client.post("/api/sync", json={"sources": ["unknown"]}, headers=headers).status_code == 400
    assert client.post("/api/sync", json={"sources": "rocketjobs"}, headers=headers).status_code == 400

    try:
        assert client.post("/api/sync", json={"sources": ["justjoin"]}, headers=headers).status_code == 202
        for _ in range(100):
            if service.operations.current()["status"] != "running":
                break
            time.sleep(0.01)
        assert service.operations.current()["status"] == "done"
        assert [source.calls for source in sources] == [0, 1, 0]
    finally:
        service.operations.executor.shutdown(wait=True)


def test_sync_persists_counts_and_rejection_reasons_by_source(tmp_path):
    class FakeSource:
        source_id = "pracuj"
        display_name = "Pracuj.pl"

        def offers(self, progress=None):
            yield {**OFFER, "source": "pracuj", "url": "https://www.pracuj.pl/praca/python,oferta,1"}
            yield {**OFFER, "source": "pracuj", "url": "https://www.pracuj.pl/praca/python,oferta,2", "remote_mode": "hybrid"}

    store = Store(tmp_path / "db.sqlite3")
    store.set_setting("search_profile", SAMPLE_SEARCH_PROFILE)
    service = JobService(store, source=FakeSource())
    result = service.sync(lambda *_args: None)

    assert (result["seen"], result["matched"], result["skipped"], result["new"]) == (2, 1, 1, 1)
    assert result["sources"][0]["skip_reasons"] == {"Oferta nie potwierdza pracy w pełni zdalnej": 1}
    assert store.get_setting("last_sync_report") == result
    assert create_app(service=service).test_client().get("/api/bootstrap").json["last_sync_report"] == result


def test_failed_sync_persists_partial_report(tmp_path):
    class FailingSource:
        source_id = "pracuj"
        display_name = "Pracuj.pl"

        def offers(self, progress=None):
            yield {**OFFER, "source": "pracuj", "url": "https://www.pracuj.pl/praca/python,oferta,3"}
            raise RuntimeError("Źródło nie odpowiada")

    store = Store(tmp_path / "db.sqlite3")
    store.set_setting("search_profile", SAMPLE_SEARCH_PROFILE)
    service = JobService(store, source=FailingSource())

    try:
        service.sync(lambda *_args: None)
    except RuntimeError as exc:
        assert str(exc) == "Źródło nie odpowiada"
    else:
        raise AssertionError("Synchronizacja powinna zgłosić błąd")

    report = store.get_setting("last_sync_report")
    assert report["status"] == "error"
    assert report["new"] == 1
    assert report["sources"][0]["new"] == 1


def test_database_reset_requires_phrase_and_creates_recoverable_backup(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.upsert_offer(OFFER)
    store.set_setting("resume_path", "/tmp/custom-resume.pdf")
    app = create_app(storage_path=store.path)
    client = app.test_client()
    token = client.get("/api/bootstrap").json["token"]
    headers = {"X-Local-Token": token}

    denied = client.post("/api/database/reset", json={"confirmation": "RESET"}, headers=headers)
    assert denied.status_code == 400
    assert len(store.list_offers()) == 1

    response = client.post(
        "/api/database/reset",
        json={"confirmation": "USUŃ WSZYSTKO"},
        headers=headers,
    )
    assert response.status_code == 200
    backup_path = tmp_path / "backups" / response.json["backup_name"]
    assert backup_path.is_file()
    assert store.list_offers() == []
    assert store.applications() == []
    assert store.get_setting("resume_path") == ""

    backup = Store(backup_path)
    assert len(backup.list_offers()) == 1
    assert backup.get_setting("resume_path") == "/tmp/custom-resume.pdf"


def test_unknown_salary_cannot_be_recommended_to_apply(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    candidate = SAMPLE_CANDIDATE_PROFILE
    profile = SAMPLE_SEARCH_PROFILE
    offer = {**OFFER, "salary": {"minimum": None, "maximum": None, "currency": None, "unit": None, "basis": "unknown"}}
    result = normalize_result(evaluation(), offer, profile, candidate)
    assert result["recommendation"] == "sprawdź"
    assert "wynagrodzenia" in result["unknowns"][0]


def test_hybrid_description_overrides_remote_metadata(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    candidate = SAMPLE_CANDIDATE_PROFILE
    profile = SAMPLE_SEARCH_PROFILE
    offer = {**OFFER, "description": "Hybrid by design. Two days per week in the office."}
    result = normalize_result(evaluation(), offer, profile, candidate)
    assert result["recommendation"] == "pomiń"
    assert result["score"] == 0
    assert "hybrydowy" in result["gaps"][0]


def test_hard_remote_validation_skips_ai_evaluator(tmp_path):
    class CountingEvaluator:
        name = "test"

        def __init__(self):
            self.calls = 0

        def evaluate(self, _offer, _profile, _candidate):
            self.calls += 1
            return evaluation()

    store = Store(tmp_path / "db.sqlite3")
    store.upsert_offer({**OFFER, "description": "Remote label, but hybrid by design."})
    offer_id = store.list_offers()[0]["id"]
    evaluator = CountingEvaluator()
    service = JobService(store, evaluator=evaluator)

    result = service.evaluate([offer_id], lambda *_args: None)

    assert result == {"completed": [offer_id], "errors": []}
    assert evaluator.calls == 0
    saved = store.get_offer(offer_id)["evaluation"]
    assert saved["recommendation"] == "pomiń"
    assert saved["score"] == 0


def test_stale_evaluation_cannot_be_approved(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.upsert_offer(OFFER)
    offer_id = store.list_offers()[0]["id"]
    store.save_evaluation(offer_id, evaluation(), "test")
    store.upsert_offer({**OFFER, "description": "Changed role requirements"})
    app = create_app(storage_path=store.path)
    client = app.test_client()
    token = client.get("/api/bootstrap").json["token"]
    response = client.post(f"/api/offers/{offer_id}/decision", json={"decision": "approved"}, headers={"X-Local-Token": token})
    assert response.status_code == 400


def test_reevaluation_skips_rejected_and_submitted_but_keeps_pending_approved(tmp_path):
    class FakeEvaluator:
        name = "test"

        def __init__(self):
            self.evaluated_ids = []

        def evaluate(self, offer, _profile, _candidate):
            self.evaluated_ids.append(offer["id"])
            return evaluation()

    store = Store(tmp_path / "db.sqlite3")
    store.set_setting("candidate_profile", SAMPLE_CANDIDATE_PROFILE)
    ids = {}
    for state in ("open", "approved", "rejected", "submitted"):
        original = {**OFFER, "url": f"{OFFER['url']}-{state}", "title": f"Python Developer {state}"}
        store.upsert_offer(original)
        offer_id = next(offer["id"] for offer in store.list_offers() if offer["url"] == original["url"])
        ids[state] = offer_id
        store.save_evaluation(offer_id, evaluation(), "test")
        if state != "open":
            store.set_decision(offer_id, "approved" if state in {"approved", "submitted"} else "rejected")
        if state == "submitted":
            store.mark_submitted(offer_id)
        store.upsert_offer({**original, "description": "Updated requirements for Python and Vue"})
        assert store.get_offer(offer_id)["evaluation_stale"]

    evaluator = FakeEvaluator()
    result = JobService(store, evaluator=evaluator).evaluate(list(ids.values()), lambda *_args: None)

    assert set(result["completed"]) == {ids["open"], ids["approved"]}
    assert {error["id"] for error in result["errors"]} == {ids["rejected"], ids["submitted"]}
    assert set(evaluator.evaluated_ids) == {ids["open"], ids["approved"]}
    assert store.get_offer(ids["rejected"])["evaluation_stale"]
    assert store.get_offer(ids["submitted"])["evaluation_stale"]


def test_bulk_evaluation_processes_every_requested_offer(tmp_path):
    class FakeEvaluator:
        name = "test"

        def __init__(self):
            self.evaluated_ids = []
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()
            self.two_started = threading.Event()

        def evaluate(self, offer, _profile, _candidate):
            with self.lock:
                self.evaluated_ids.append(offer["id"])
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                if self.active == 2:
                    self.two_started.set()
            self.two_started.wait(timeout=1)
            try:
                return evaluation()
            finally:
                with self.lock:
                    self.active -= 1

    store = Store(tmp_path / "db.sqlite3")
    store.set_setting("candidate_profile", SAMPLE_CANDIDATE_PROFILE)
    store.upsert_offer(OFFER)
    store.upsert_offer({
        **OFFER,
        "url": "https://rocketjobs.pl/oferta-pracy/second-python-developer",
        "title": "Senior Python Developer",
    })
    evaluator = FakeEvaluator()
    service = JobService(store, evaluator=evaluator)
    app = create_app(service=service)
    client = app.test_client()
    token = client.get("/api/bootstrap").json["token"]
    offer_ids = [offer["id"] for offer in store.list_offers()]

    response = client.post(
        "/api/evaluate",
        json={"ids": offer_ids},
        headers={"X-Local-Token": token},
    )

    assert response.status_code == 202
    deadline = time.monotonic() + 2
    state = service.operations.current()
    while state["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        state = service.operations.current()
    assert state["status"] == "done"
    assert state["result"] == {"completed": offer_ids, "errors": []}
    assert set(evaluator.evaluated_ids) == set(offer_ids)
    assert evaluator.max_active == 2
    assert state["current"] == 2
    assert state["total"] == 2
    assert state["started_at"]
    assert state["updated_at"]
    assert all(store.get_offer(offer_id)["evaluation"] for offer_id in offer_ids)


def test_bulk_decisions_use_saved_thresholds_and_preserve_manual_decisions(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    scores = [49, 50, 69, 70, 89, 95]
    ids = []
    for score in scores:
        store.upsert_offer({**OFFER, "url": f"{OFFER['url']}-{score}", "title": f"Python {score}"})
        offer_id = next(offer["id"] for offer in store.list_offers() if offer["title"] == f"Python {score}")
        store.save_evaluation(offer_id, {**evaluation(), "score": score}, "test")
        ids.append(offer_id)
    store.set_decision(ids[-1], "rejected")
    store.upsert_offer({**OFFER, "url": f"{OFFER['url']}-stale", "title": "Stale"})
    stale_id = next(offer["id"] for offer in store.list_offers() if offer["title"] == "Stale")
    store.save_evaluation(stale_id, {**evaluation(), "score": 99}, "test")
    store.upsert_offer({**OFFER, "url": f"{OFFER['url']}-stale", "title": "Stale", "description": "Changed"})

    app = create_app(storage_path=store.path)
    client = app.test_client()
    bootstrap = client.get("/api/bootstrap").json
    assert bootstrap["decision_profile"] == {"approve_min_score": 70, "reject_below_score": 50}
    headers = {"X-Local-Token": bootstrap["token"]}
    assert client.post("/api/offers/bulk-decision", json={"decision": "approved"}).status_code == 403
    response = client.post("/api/offers/bulk-decision", json={"decision": "approved"}, headers=headers)
    assert response.status_code == 200
    assert response.json["count"] == 2
    assert set(response.json["ids"]) == {ids[3], ids[4]}
    assert store.get_offer(ids[-1])["decision"] == "rejected"
    assert store.get_offer(stale_id)["decision"] == "none"

    response = client.post("/api/offers/bulk-decision", json={"decision": "rejected"}, headers=headers)
    assert response.json["ids"] == [ids[0]]
    assert store.get_offer(ids[1])["decision"] == "none"
    assert store.get_offer(ids[2])["decision"] == "none"
    assert len(store.applications()) == 2


def test_configurable_decision_threshold_validation(tmp_path):
    app = create_app(storage_path=tmp_path / "db.sqlite3")
    client = app.test_client()
    headers = {"X-Local-Token": client.get("/api/bootstrap").json["token"]}
    invalid = client.put(
        "/api/decision-profile",
        json={"approve_min_score": 60, "reject_below_score": 80},
        headers=headers,
    )
    assert invalid.status_code == 400
    assert client.get("/api/bootstrap").json["decision_profile"]["approve_min_score"] == 70
    valid = client.put(
        "/api/decision-profile",
        json={"approve_min_score": 75, "reject_below_score": 40},
        headers=headers,
    )
    assert valid.status_code == 200
    assert valid.json == {"approve_min_score": 75, "reject_below_score": 40}


def test_offer_api_remains_responsive_during_ai_evaluation(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class WaitingEvaluator:
        name = "test"

        def evaluate(self, _offer, _profile, _candidate):
            started.set()
            assert release.wait(timeout=3)
            return evaluation()

    store = Store(tmp_path / "db.sqlite3")
    store.set_setting("candidate_profile", SAMPLE_CANDIDATE_PROFILE)
    store.upsert_offer(OFFER)
    service = JobService(store, evaluator=WaitingEvaluator())
    client = create_app(service=service).test_client()
    offer_id = store.list_offers()[0]["id"]
    token = client.get("/api/bootstrap").json["token"]
    try:
        response = client.post("/api/evaluate", json={"ids": [offer_id]}, headers={"X-Local-Token": token})
        assert response.status_code == 202
        assert started.wait(timeout=2)
        assert client.get("/api/operation").json["status"] == "running"
        assert client.get("/api/offers").status_code == 200
        assert client.get("/api/offers").json[0]["evaluation"] is None
        candidate = store.get_setting("candidate_profile")
        store.set_setting("candidate_profile", {**candidate, "summary": "Profil zmieniony podczas oceny"})
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while service.operations.current()["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.operations.current()["status"] == "done"
    assert client.get("/api/offers").json[0]["evaluation"]["score"] == 89
    assert client.get("/api/offers").json[0]["evaluation_stale"]
