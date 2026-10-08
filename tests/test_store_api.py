import threading
import time

from getmeajob.api import create_app
from getmeajob.evaluation import normalize_result
from getmeajob.service import JobService
from getmeajob.store import Store


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


def test_approval_requires_evaluation_and_submission_confirmation(tmp_path):
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
    assert client.post(f"/api/applications/{offer_id}/submitted", json={"confirmation": ""}, headers=headers).status_code == 400
    assert client.post(f"/api/applications/{offer_id}/submitted", json={"confirmation": "Dziękujemy za aplikację"}, headers=headers).status_code == 200
    assert client.post(f"/api/applications/{offer_id}/submitted", json={"confirmation": "drugi raz"}, headers=headers).status_code == 400


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
    candidate = store.get_setting("candidate_profile")
    profile = store.get_setting("search_profile")
    offer = {**OFFER, "salary": {"minimum": None, "maximum": None, "currency": None, "unit": None, "basis": "unknown"}}
    result = normalize_result(evaluation(), offer, profile, candidate)
    assert result["recommendation"] == "sprawdź"
    assert "wynagrodzenia" in result["unknowns"][0]


def test_hybrid_description_overrides_remote_metadata(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    candidate = store.get_setting("candidate_profile")
    profile = store.get_setting("search_profile")
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
