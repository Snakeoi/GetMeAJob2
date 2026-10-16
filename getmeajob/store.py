from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DEFAULT_CANDIDATE_PROFILE, DEFAULT_DECISION_PROFILE, DEFAULT_SEARCH_PROFILE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offers (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    description TEXT NOT NULL,
                    location TEXT NOT NULL,
                    remote_mode TEXT NOT NULL,
                    contract_types_json TEXT NOT NULL,
                    salary_json TEXT NOT NULL,
                    posted_at TEXT,
                    expires_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    source_updated_at TEXT,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    decision TEXT NOT NULL DEFAULT 'none',
                    raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS offers_status_idx ON offers(status, decision, last_seen_at);
                CREATE TABLE IF NOT EXISTS offer_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    offer_id TEXT NOT NULL REFERENCES offers(id),
                    captured_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    offer_id TEXT NOT NULL REFERENCES offers(id),
                    created_at TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL,
                    offer_hash TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS evaluations_offer_idx ON evaluations(offer_id, id DESC);
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    offer_id TEXT NOT NULL UNIQUE REFERENCES offers(id),
                    status TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    submitted_at TEXT,
                    confirmation TEXT,
                    notes TEXT
                );
                """
            )
            conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", ("search_profile", json.dumps(DEFAULT_SEARCH_PROFILE)))
            conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", ("candidate_profile", json.dumps(DEFAULT_CANDIDATE_PROFILE)))
            conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", ("resume_path", json.dumps("")))
            conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", ("decision_profile", json.dumps(DEFAULT_DECISION_PROFILE)))

    def get_setting(self, key: str) -> Any:
        with self.connection() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO settings(key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def set_resume(self, path: Path, original_name: str) -> None:
        with self.connection() as conn:
            conn.executemany(
                "INSERT INTO settings(key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (
                    ("resume_path", json.dumps(str(path))),
                    ("resume_original_name", json.dumps(original_name, ensure_ascii=False)),
                ),
            )

    def set_candidate_profile(self, profile: dict[str, Any], resume_hash: str | None = None) -> None:
        """Save reviewed facts and their source CV in one transaction."""
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO settings(key, value_json) VALUES ('candidate_profile', ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (json.dumps(profile, ensure_ascii=False),),
            )
            if resume_hash is not None:
                conn.execute(
                    "INSERT INTO settings(key, value_json) VALUES ('facts_resume_hash', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                    (json.dumps(resume_hash),),
                )

    def reset_all(self) -> Path:
        """Back up the database, then restore it to a fresh-install state."""
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = backup_dir / f"getmeajob-before-reset-{timestamp}.sqlite3"

        with sqlite3.connect(self.path, timeout=30) as source, sqlite3.connect(backup_path) as destination:
            source.backup(destination)

        with self.connection() as conn:
            conn.execute("DELETE FROM applications")
            conn.execute("DELETE FROM evaluations")
            conn.execute("DELETE FROM offer_snapshots")
            conn.execute("DELETE FROM offers")
            conn.execute("DELETE FROM settings")
            conn.executemany(
                "INSERT INTO settings(key, value_json) VALUES (?, ?)",
                (
                    ("search_profile", json.dumps(DEFAULT_SEARCH_PROFILE, ensure_ascii=False)),
                    ("candidate_profile", json.dumps(DEFAULT_CANDIDATE_PROFILE, ensure_ascii=False)),
                    ("resume_path", json.dumps("")),
                    ("decision_profile", json.dumps(DEFAULT_DECISION_PROFILE, ensure_ascii=False)),
                ),
            )
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('offer_snapshots', 'evaluations', 'applications')"
            )
        return backup_path

    def upsert_offer(self, offer: dict[str, Any]) -> str:
        """Return 'new', 'changed', or 'unchanged'."""
        payload = {
            key: offer.get(key)
            for key in (
                "url", "title", "company", "description", "location", "remote_mode",
                "contract_types", "salary", "posted_at", "expires_at",
            )
        }
        content_hash = stable_hash(payload)
        offer_id = hashlib.sha256(offer["url"].encode()).hexdigest()[:24]
        now = utc_now()
        with self.connection() as conn:
            old = conn.execute("SELECT content_hash FROM offers WHERE id = ?", (offer_id,)).fetchone()
            if old and old["content_hash"] == content_hash:
                conn.execute("UPDATE offers SET last_seen_at = ?, status = 'active' WHERE id = ?", (now, offer_id))
                return "unchanged"
            values = (
                offer_id, offer.get("source", "rocketjobs"), offer["url"], offer["title"],
                offer.get("company", ""), offer.get("description", ""), offer.get("location", ""),
                offer.get("remote_mode", "unknown"), json.dumps(offer.get("contract_types", [])),
                json.dumps(offer.get("salary", {})), offer.get("posted_at"), offer.get("expires_at"),
                now, now, offer.get("source_updated_at"), content_hash, "active", "none",
                json.dumps(offer, ensure_ascii=False),
            )
            conn.execute(
                """
                INSERT INTO offers (
                    id, source, url, title, company, description, location, remote_mode,
                    contract_types_json, salary_json, posted_at, expires_at, first_seen_at,
                    last_seen_at, source_updated_at, content_hash, status, decision, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, company=excluded.company,
                    description=excluded.description, location=excluded.location,
                    remote_mode=excluded.remote_mode,
                    contract_types_json=excluded.contract_types_json,
                    salary_json=excluded.salary_json,
                    posted_at=excluded.posted_at, expires_at=excluded.expires_at,
                    last_seen_at=excluded.last_seen_at,
                    source_updated_at=excluded.source_updated_at,
                    content_hash=excluded.content_hash, status='active', raw_json=excluded.raw_json
                """,
                values,
            )
            conn.execute(
                "INSERT INTO offer_snapshots(offer_id, captured_at, content_hash, data_json) VALUES (?, ?, ?, ?)",
                (offer_id, now, content_hash, json.dumps(offer, ensure_ascii=False)),
            )
            return "changed" if old else "new"

    def _offer(self, row: sqlite3.Row, evaluation: sqlite3.Row | None = None) -> dict[str, Any]:
        result = dict(row)
        result["contract_types"] = json.loads(result.pop("contract_types_json"))
        result["salary"] = json.loads(result.pop("salary_json"))
        result.pop("raw_json")
        if evaluation:
            result["evaluation"] = json.loads(evaluation["result_json"])
            result["evaluated_at"] = evaluation["created_at"]
            result["evaluation_stale"] = (
                evaluation["offer_hash"] != result["content_hash"]
                or evaluation["profile_hash"] != stable_hash(self.get_setting("search_profile"))
                or evaluation["candidate_hash"] != stable_hash(self.get_setting("candidate_profile"))
            )
        else:
            result["evaluation"] = None
            result["evaluated_at"] = None
            result["evaluation_stale"] = False
        return result

    def list_offers(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM offers WHERE status = 'active' ORDER BY first_seen_at DESC, title").fetchall()
            result = []
            for row in rows:
                evaluation = conn.execute(
                    "SELECT * FROM evaluations WHERE offer_id = ? ORDER BY id DESC LIMIT 1", (row["id"],)
                ).fetchone()
                result.append(self._offer(row, evaluation))
            return result

    def get_offer(self, offer_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
            if not row:
                return None
            evaluation = conn.execute(
                "SELECT * FROM evaluations WHERE offer_id = ? ORDER BY id DESC LIMIT 1", (offer_id,)
            ).fetchone()
            return self._offer(row, evaluation)

    def save_evaluation(
        self, offer_id: str, result: dict[str, Any], agent: str,
        *, profile_hash: str | None = None, candidate_hash: str | None = None,
        offer_hash: str | None = None,
    ) -> None:
        offer = self.get_offer(offer_id)
        if not offer:
            raise ValueError("Offer not found")
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO evaluations
                (offer_id, created_at, profile_hash, candidate_hash, offer_hash, agent, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    offer_id, utc_now(), profile_hash or stable_hash(self.get_setting("search_profile")),
                    candidate_hash or stable_hash(self.get_setting("candidate_profile")), offer_hash or offer["content_hash"],
                    agent, json.dumps(result, ensure_ascii=False),
                ),
            )

    def set_decision(self, offer_id: str, decision: str) -> None:
        if decision not in {"none", "approved", "rejected"}:
            raise ValueError("Invalid decision")
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM offers WHERE id = ?", (offer_id,)).fetchone():
                raise ValueError("Offer not found")
            application = conn.execute("SELECT status FROM applications WHERE offer_id = ?", (offer_id,)).fetchone()
            if application and application["status"] == "submitted":
                raise ValueError("Wysłanej aplikacji nie można ponownie zatwierdzić ani odrzucić")
            conn.execute("UPDATE offers SET decision = ? WHERE id = ?", (decision, offer_id))
            if decision == "approved":
                conn.execute(
                    "INSERT INTO applications(offer_id, status, approved_at) VALUES (?, 'approved', ?) "
                    "ON CONFLICT(offer_id) DO UPDATE SET status='approved', approved_at=excluded.approved_at",
                    (offer_id, utc_now()),
                )
            else:
                conn.execute("DELETE FROM applications WHERE offer_id = ? AND status = 'approved'", (offer_id,))

    def bulk_decide(self, decision: str) -> list[str]:
        """Apply the saved score rule to pending offers with current evaluations only."""
        if decision not in {"approved", "rejected"}:
            raise ValueError("Invalid bulk decision")
        with self.connection() as conn:
            settings = {
                row["key"]: json.loads(row["value_json"])
                for row in conn.execute(
                    "SELECT key, value_json FROM settings WHERE key IN ('search_profile', 'candidate_profile', 'decision_profile')"
                )
            }
            profile_hash = stable_hash(settings["search_profile"])
            candidate_hash = stable_hash(settings["candidate_profile"])
            threshold = settings["decision_profile"]["approve_min_score" if decision == "approved" else "reject_below_score"]
            rows = conn.execute(
                """SELECT o.id, o.content_hash, e.profile_hash, e.candidate_hash,
                          e.offer_hash, e.result_json
                   FROM offers o
                   JOIN evaluations e ON e.id = (
                       SELECT id FROM evaluations WHERE offer_id = o.id ORDER BY id DESC LIMIT 1
                   )
                   LEFT JOIN applications a ON a.offer_id = o.id
                   WHERE o.status = 'active' AND o.decision = 'none'
                     AND (a.id IS NULL OR a.status != 'submitted')"""
            ).fetchall()
            selected = []
            for row in rows:
                if (row["offer_hash"], row["profile_hash"], row["candidate_hash"]) != (
                    row["content_hash"], profile_hash, candidate_hash
                ):
                    continue
                score = json.loads(row["result_json"]).get("score")
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    continue
                if (decision == "approved" and score >= threshold) or (decision == "rejected" and score < threshold):
                    selected.append(row["id"])
            now = utc_now()
            for offer_id in selected:
                conn.execute("UPDATE offers SET decision = ? WHERE id = ?", (decision, offer_id))
                if decision == "approved":
                    conn.execute(
                        "INSERT INTO applications(offer_id, status, approved_at) VALUES (?, 'approved', ?) "
                        "ON CONFLICT(offer_id) DO UPDATE SET status='approved', approved_at=excluded.approved_at",
                        (offer_id, now),
                    )
            return selected

    def approved_offers(self) -> list[dict[str, Any]]:
        return [offer for offer in self.list_offers() if offer["decision"] == "approved"]

    def mark_submitted(self, offer_id: str, confirmation: str = "", notes: str = "") -> None:
        with self.connection() as conn:
            row = conn.execute("SELECT status FROM applications WHERE offer_id = ?", (offer_id,)).fetchone()
            if not row or row["status"] != "approved":
                raise ValueError("Offer is not approved for submission")
            conn.execute(
                "UPDATE applications SET status='submitted', submitted_at=?, confirmation=?, notes=? WHERE offer_id=?",
                (utc_now(), confirmation, notes, offer_id),
            )

    def mark_not_submitted(self, offer_id: str) -> None:
        with self.connection() as conn:
            result = conn.execute(
                "UPDATE applications SET status='approved', submitted_at=NULL, confirmation='', notes='' "
                "WHERE offer_id=? AND status='submitted'",
                (offer_id,),
            )
            if result.rowcount != 1:
                raise ValueError("Aplikacja nie jest oznaczona jako wysłana")

    def applications(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM applications ORDER BY approved_at DESC")]
