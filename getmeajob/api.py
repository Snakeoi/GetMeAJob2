from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file, send_from_directory

from .config import DEFAULT_SEARCH_PROFILE, data_dir
from .resume_facts import extract_resume_facts
from .search_profile import validate_search_profile
from .service import BusyError, JobService
from .store import Store


def resume_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resume_display_name(store: Store, resume: str) -> tuple[str | None, bool]:
    if not resume:
        return None, False
    original_name = store.get_setting("resume_original_name")
    if original_name:
        return original_name, True
    if Path(resume).name != "resume.pdf":
        return Path(resume).name, True
    return Path(resume).name, False


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
        resume_file = Path(resume) if resume else None
        current_hash = resume_hash(resume_file) if resume_file and resume_file.is_file() else None
        resume_name, resume_name_known = resume_display_name(store, resume)
        return jsonify({
            "token": app.config["LOCAL_TOKEN"],
            "search_profile": store.get_setting("search_profile"),
            "decision_profile": store.get_setting("decision_profile"),
            "candidate_profile": store.get_setting("candidate_profile"),
            "resume_name": resume_name,
            "resume_name_known": resume_name_known,
            "resume_facts_status": (
                "missing" if current_hash is None else
                "ready" if current_hash == store.get_setting("facts_resume_hash") else "needs-extraction"
            ),
            "operation": service.operations.current(),
            "last_sync_report": store.get_setting("last_sync_report"),
            "sources": service.available_sources(),
        })

    @app.get("/api/offers")
    def list_offers() -> Any:
        return jsonify(store.list_offers())

    @app.get("/api/operation")
    def current_operation() -> Any:
        return jsonify(service.operations.current())

    @app.post("/api/sync")
    def sync() -> Any:
        payload = request.get_json(silent=True) or {}
        source_ids = payload.get("sources")
        service.selected_sources(source_ids)
        if not store.get_setting("search_profile").get("roles"):
            raise ValueError("Najpierw ustaw stanowiska w Ustawieniach")
        service.operations.start("sync", lambda report: service.sync(report, source_ids))
        return jsonify({"started": True}), 202

    @app.post("/api/evaluate")
    def evaluate() -> Any:
        payload = request.get_json(silent=True) or {}
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
            raise ValueError("Provide a non-empty list of offer IDs")
        if not store.get_setting("candidate_profile").get("facts"):
            raise ValueError("Najpierw wgraj CV i zapisz fakty kandydata w Ustawieniach")
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
        store.mark_submitted(offer_id, confirmation, str(payload.get("notes") or ""))
        return jsonify({"ok": True})

    @app.post("/api/applications/<offer_id>/not-submitted")
    def mark_not_submitted(offer_id: str) -> Any:
        store.mark_not_submitted(offer_id)
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
        for key in set(current) | set(DEFAULT_SEARCH_PROFILE):
            if key in payload:
                current[key] = payload[key]
        if "work_modes" in current:
            validate_search_profile(current)
        elif not isinstance(current["excluded_terms"], list):
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
        extracted_hash = payload.pop("extracted_resume_hash", None)
        if not isinstance(payload.get("facts"), list):
            raise ValueError("Fakty z CV muszą być listą")
        for fact in payload["facts"]:
            if not isinstance(fact, dict) or not fact.get("id") or not fact.get("text"):
                raise ValueError("Każdy fakt wymaga id i tekstu")
        if extracted_hash is not None:
            resume = store.get_setting("resume_path")
            if (not isinstance(extracted_hash, str) or not resume or not Path(resume).is_file()
                    or extracted_hash != resume_hash(Path(resume))):
                raise ValueError("CV zmieniło się od czasu analizy. Wyciągnij fakty ponownie.")
        store.set_candidate_profile(payload, extracted_hash)
        return jsonify(payload)

    @app.post("/api/resume")
    def upload_resume() -> Any:
        if service.operations.current()["status"] == "running" and service.operations.current()["kind"] == "resume-facts":
            raise BusyError("Poczekaj na zakończenie analizy CV")
        file = request.files.get("file")
        if not file or not file.filename or not file.filename.lower().endswith(".pdf"):
            raise ValueError("Wybierz plik CV w formacie PDF")
        contents = file.read()
        if not contents.startswith(b"%PDF-"):
            raise ValueError("Plik nie jest poprawnym PDF")
        original_name = Path(file.filename.replace("\\", "/")).name
        original_name = "".join(char for char in original_name if ord(char) >= 32 and ord(char) != 127).strip()
        original_name = f"{original_name[:-4][:196]}{original_name[-4:]}" if original_name else "CV.pdf"
        destination = store.path.parent / "resume.pdf"
        destination.write_bytes(contents)
        store.set_resume(destination, original_name)
        return jsonify({
            "resume_name": original_name,
            "resume_name_known": True,
            "resume_facts_status": "ready" if resume_hash(destination) == store.get_setting("facts_resume_hash") else "needs-extraction",
        })

    @app.get("/api/resume/preview")
    def resume_preview() -> Any:
        if request.headers.get("X-Local-Token") != app.config["LOCAL_TOKEN"]:
            return jsonify({"error": "Invalid local session token"}), 403
        resume = store.get_setting("resume_path")
        if not resume or not Path(resume).is_file():
            raise ValueError("Brak CV do podglądu")
        name, _ = resume_display_name(store, resume)
        response = send_file(resume, mimetype="application/pdf", as_attachment=False, download_name=name)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.post("/api/resume/extract-facts")
    def resume_extract_facts() -> Any:
        resume = store.get_setting("resume_path")
        if not resume or not Path(resume).is_file():
            raise ValueError("Najpierw wgraj CV w formacie PDF")
        resume_path = Path(resume)
        source_hash = resume_hash(resume_path)

        def work(report: Any) -> dict[str, Any]:
            report("Analizuję CV…")
            facts = extract_resume_facts(resume_path, service.evaluator)
            if source_hash != resume_hash(resume_path):
                raise ValueError("CV zmieniło się podczas analizy. Wyciągnij fakty ponownie.")
            return {"facts": facts, "resume_hash": source_hash}

        service.operations.start("resume-facts", work)
        return jsonify({"started": True}), 202

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
