from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from .config import data_dir
from .service import BusyError, JobService
from .store import Store


def create_app(service: JobService | None = None, storage_path: Path | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    frontend_dist = project_root / "frontend" / "dist"
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    app.config["LOCAL_TOKEN"] = secrets.token_urlsafe(32)
    if service is None:
        store = Store(storage_path or data_dir() / "getmeajob.sqlite3")
        service = JobService(store)
    store = service.store

    @app.before_request
    def local_mutation_token() -> Any:
        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("X-Local-Token") != app.config["LOCAL_TOKEN"]:
                return jsonify({"error": "Invalid local session token"}), 403
        return None

    @app.errorhandler(ValueError)
    def invalid_request(exc: ValueError) -> Any:
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(BusyError)
    def busy(exc: BusyError) -> Any:
        return jsonify({"error": str(exc)}), 409

    @app.get("/api/bootstrap")
    def bootstrap() -> Any:
        resume = store.get_setting("resume_path")
        return jsonify({
            "token": app.config["LOCAL_TOKEN"],
            "search_profile": store.get_setting("search_profile"),
            "decision_profile": store.get_setting("decision_profile"),
            "candidate_profile": store.get_setting("candidate_profile"),
            "resume_name": Path(resume).name if resume else None,
            "operation": service.operations.current(),
        })

    @app.get("/api/offers")
    def list_offers() -> Any:
        return jsonify(store.list_offers())

    @app.get("/api/operation")
    def current_operation() -> Any:
        return jsonify(service.operations.current())

    @app.post("/api/sync")
    def sync() -> Any:
        service.operations.start("sync", service.sync)
        return jsonify({"started": True}), 202

    @app.post("/api/evaluate")
    def evaluate() -> Any:
        payload = request.get_json(silent=True) or {}
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
            raise ValueError("Provide a non-empty list of offer IDs")
        service.operations.start("evaluate", lambda report: service.evaluate(ids, report))
        return jsonify({"started": True}), 202

    @app.post("/api/offers/import")
    def import_offer() -> Any:
        payload = request.get_json(silent=True) or {}
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("Podaj link do oferty")
        offer, warning = service.import_url(url)
        return jsonify({"offer": offer, "warning": warning})

    @app.post("/api/offers/<offer_id>/decision")
    def decide(offer_id: str) -> Any:
        payload = request.get_json(silent=True) or {}
        decision = payload.get("decision")
        offer = store.get_offer(offer_id)
        if not offer:
            raise ValueError("Offer not found")
        if decision == "approved" and (not offer["evaluation"] or offer["evaluation_stale"]):
            raise ValueError("Najpierw oceń aktualną wersję oferty i profilu")
        store.set_decision(offer_id, decision)
        return jsonify(store.get_offer(offer_id))

    @app.post("/api/offers/bulk-decision")
    def bulk_decision() -> Any:
        payload = request.get_json(silent=True) or {}
        changed = store.bulk_decide(payload.get("decision"))
        return jsonify({"count": len(changed), "ids": changed})

    @app.get("/api/applications")
    def applications() -> Any:
        return jsonify(store.applications())

    @app.post("/api/applications/<offer_id>/submitted")
    def mark_submitted(offer_id: str) -> Any:
        payload = request.get_json(silent=True) or {}
        confirmation = str(payload.get("confirmation") or "").strip()
        if not confirmation:
            raise ValueError("Podaj potwierdzenie wysłania aplikacji")
        store.mark_submitted(offer_id, confirmation, str(payload.get("notes") or ""))
        return jsonify({"ok": True})

    @app.post("/api/database/reset")
    def reset_database() -> Any:
        payload = request.get_json(silent=True) or {}
        if payload.get("confirmation") != "USUŃ WSZYSTKO":
            raise ValueError("Wpisz dokładnie: USUŃ WSZYSTKO")
        if service.operations.current()["status"] == "running":
            raise BusyError("Poczekaj na zakończenie bieżącej operacji")
        backup_path = store.reset_all()
        return jsonify({"ok": True, "backup_name": backup_path.name})

    @app.put("/api/search-profile")
    def set_search_profile() -> Any:
        payload = request.get_json(silent=True) or {}
        current = store.get_setting("search_profile")
        for key in current:
            if key in payload:
                current[key] = payload[key]
        if not isinstance(current["excluded_terms"], list):
            raise ValueError("Wykluczone frazy muszą być listą")
        store.set_setting("search_profile", current)
        return jsonify(current)

    @app.put("/api/decision-profile")
    def set_decision_profile() -> Any:
        payload = request.get_json(silent=True) or {}
        current = store.get_setting("decision_profile")
        for key in current:
            if key in payload:
                current[key] = payload[key]
        approve = current["approve_min_score"]
        reject = current["reject_below_score"]
        if (type(approve) is not int or type(reject) is not int
                or not 0 <= reject <= approve <= 100):
            raise ValueError("Progi muszą być liczbami całkowitymi 0–100; próg odrzucenia nie może przekraczać progu zatwierdzenia")
        store.set_setting("decision_profile", current)
        return jsonify(current)

    @app.put("/api/candidate-profile")
    def set_candidate_profile() -> Any:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload.get("facts"), list) or not payload["facts"]:
            raise ValueError("Profil musi zawierać fakty z CV")
        for fact in payload["facts"]:
            if not isinstance(fact, dict) or not fact.get("id") or not fact.get("text"):
                raise ValueError("Każdy fakt wymaga id i tekstu")
        store.set_setting("candidate_profile", payload)
        return jsonify(payload)

    @app.post("/api/resume")
    def upload_resume() -> Any:
        file = request.files.get("file")
        if not file or not file.filename or not file.filename.lower().endswith(".pdf"):
            raise ValueError("Wybierz plik CV w formacie PDF")
        contents = file.read()
        if not contents.startswith(b"%PDF-"):
            raise ValueError("Plik nie jest poprawnym PDF")
        destination = store.path.parent / "resume.pdf"
        destination.write_bytes(contents)
        store.set_setting("resume_path", str(destination))
        return jsonify({"resume_name": destination.name})

    @app.get("/")
    def index() -> Any:
        if not (frontend_dist / "index.html").exists():
            return "Frontend nie jest zbudowany. Uruchom: cd frontend && npm run build", 503
        return send_from_directory(frontend_dist, "index.html")

    @app.get("/<path:filename>")
    def static_file(filename: str) -> Any:
        if (frontend_dist / filename).is_file():
            return send_from_directory(frontend_dist, filename)
        return send_from_directory(frontend_dist, "index.html")

    return app
