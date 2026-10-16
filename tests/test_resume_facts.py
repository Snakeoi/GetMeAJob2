import json
import subprocess
import time
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from getmeajob.api import create_app
from getmeajob.evaluation import CodexEvaluator
from getmeajob.resume_facts import extract_resume_facts, extract_resume_text
from getmeajob.store import Store


def test_scanned_pdf_needs_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with path.open("wb") as output:
        writer.write(output)
    with pytest.raises(ValueError, match="OCR"):
        extract_resume_text(path)


def test_codex_facts_preserve_structured_location_and_hide_cv_on_error(tmp_path, monkeypatch):
    path = tmp_path / "cv.pdf"
    path.write_bytes(b"%PDF- fake")
    monkeypatch.setattr("getmeajob.resume_facts.extract_resume_text", lambda _: "PRIVATE CV " * 20)

    def successful_run(command, **kwargs):
        assert "PRIVATE CV" in kwargs["input"]
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({"facts": [
            {"text": "Flask w projekcie", "kind": "general", "city": "", "country": ""},
            {"text": "Bydgoszcz, Polska", "kind": "location", "city": "Bydgoszcz", "country": "Polska"},
        ]}))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", successful_run)
    facts = extract_resume_facts(path, CodexEvaluator(executable="codex"))
    assert facts == [
        {"id": "cv-1", "text": "Flask w projekcie"},
        {"id": "cv-2", "text": "Bydgoszcz, Polska", "kind": "location", "city": "Bydgoszcz", "country": "Polska"},
    ]

    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(
        command, 1, "PRIVATE CV", "PRIVATE CV",
    ))
    with pytest.raises(RuntimeError) as exc:
        extract_resume_facts(path, CodexEvaluator(executable="codex"))
    assert "PRIVATE CV" not in str(exc.value)


def test_extract_endpoint_returns_draft_without_changing_profile(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite3")
    path = tmp_path / "resume.pdf"
    path.write_bytes(b"%PDF- fake")
    store.set_setting("resume_path", str(path))
    original = store.get_setting("candidate_profile")
    expected = [{"id": "cv-1", "text": "Nowy fakt"}]
    monkeypatch.setattr("getmeajob.api.extract_resume_facts", lambda *args: expected)
    client = create_app(storage_path=store.path).test_client()
    headers = {"X-Local-Token": client.get("/api/bootstrap").json["token"]}
    assert client.get("/api/bootstrap").json["resume_facts_status"] == "needs-extraction"
    assert client.get("/api/bootstrap").json["resume_name"] == "resume.pdf"
    assert client.get("/api/bootstrap").json["resume_name_known"] is False
    assert client.get("/api/resume/preview").status_code == 403
    preview = client.get("/api/resume/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.mimetype == "application/pdf"
    assert preview.data == b"%PDF- fake"
    assert preview.headers["Cache-Control"] == "no-store"
    assert client.post("/api/resume/extract-facts").status_code == 403
    assert client.post("/api/resume/extract-facts", headers=headers).status_code == 202
    for _ in range(100):
        operation = client.get("/api/operation").json
        if operation["status"] != "running":
            break
        time.sleep(0.01)
    assert operation["status"] == "done"
    assert operation["result"]["facts"] == expected
    assert store.get_setting("candidate_profile") == original
    assert client.get("/api/bootstrap").json["resume_facts_status"] == "needs-extraction"

    draft = {**original, "facts": expected, "extracted_resume_hash": operation["result"]["resume_hash"]}
    assert client.put("/api/candidate-profile", json=draft, headers=headers).status_code == 200
    assert client.get("/api/bootstrap").json["resume_facts_status"] == "ready"
    assert "extracted_resume_hash" not in store.get_setting("candidate_profile")
    assert create_app(storage_path=store.path).test_client().get("/api/bootstrap").json["resume_facts_status"] == "ready"

    same_cv = {"file": (BytesIO(b"%PDF- fake"), "new-name.pdf")}
    upload = client.post("/api/resume", data=same_cv, headers=headers).json
    assert upload["resume_facts_status"] == "ready"
    assert upload["resume_name"] == "new-name.pdf"
    assert upload["resume_name_known"] is True
    assert create_app(storage_path=store.path).test_client().get("/api/bootstrap").json["resume_name"] == "new-name.pdf"
    preview = client.get("/api/resume/preview", headers=headers)
    assert preview.data == b"%PDF- fake"
    assert "new-name.pdf" in preview.headers["Content-Disposition"]
    different_cv = {"file": (BytesIO(b"%PDF- different"), "new-name.pdf")}
    assert client.post("/api/resume", data=different_cv, headers=headers).json["resume_facts_status"] == "needs-extraction"
    assert client.get("/api/bootstrap").json["resume_facts_status"] == "needs-extraction"
    assert client.put("/api/candidate-profile", json=draft, headers=headers).status_code == 400
    assert client.get("/api/bootstrap").json["resume_facts_status"] == "needs-extraction"


def test_upload_keeps_original_filename_and_preview_uses_current_pdf(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    client = create_app(storage_path=store.path).test_client()
    headers = {"X-Local-Token": client.get("/api/bootstrap").json["token"]}
    assert client.get("/api/resume/preview", headers=headers).status_code == 400
    upload = client.post(
        "/api/resume",
        data={"file": (BytesIO(b"%PDF- version one"), "CV Janusz Ł.PDF")},
        headers=headers,
    )
    assert upload.status_code == 200
    assert upload.json["resume_name"] == "CV Janusz Ł.PDF"
    assert store.get_setting("resume_original_name") == "CV Janusz Ł.PDF"
    assert store.get_setting("resume_path") == str(tmp_path / "resume.pdf")
    assert client.get("/api/resume/preview", headers=headers).data == b"%PDF- version one"

    replacement = client.post(
        "/api/resume",
        data={"file": (BytesIO(b"%PDF- version two"), "folder/Newest CV.pdf")},
        headers=headers,
    )
    assert replacement.json["resume_name"] == "Newest CV.pdf"
    assert client.get("/api/resume/preview", headers=headers).data == b"%PDF- version two"


def test_legacy_resume_uses_file_name_instead_of_pdf_title(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    path = tmp_path / "resume.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_metadata({"/Title": "Janusz CV 2026"})
    with path.open("wb") as output:
        writer.write(output)
    store.set_setting("resume_path", str(path))
    bootstrap = create_app(storage_path=store.path).test_client().get("/api/bootstrap").json
    assert bootstrap["resume_name"] == "resume.pdf"
    assert bootstrap["resume_name_known"] is False
