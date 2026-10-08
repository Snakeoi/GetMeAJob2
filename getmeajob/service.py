from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .evaluation import CodexEvaluator
from .remote import assess_remote_requirement, remote_rejection_result
from .sources.justjoin import JustJoinSource, parse_job_page as parse_justjoin_page
from .sources.rocketjobs import RocketJobsSource, parse_job_page as parse_rocketjobs_page, prefilter
from .store import Store, stable_hash


class BusyError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperationRunner:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="getmeajob")
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {
            "kind": None, "status": "idle", "message": "", "current": 0, "total": 0,
            "started_at": None, "updated_at": None,
        }

    def start(self, kind: str, work: Callable[[Callable[..., None]], Any]) -> None:
        with self.lock:
            if self.state["status"] == "running":
                raise BusyError("Another operation is running")
            now = utc_now()
            self.state = {
                "kind": kind, "status": "running", "message": "Start", "current": 0, "total": 0,
                "started_at": now, "updated_at": now,
            }

        def report(message: str, current: int | None = None, total: int | None = None) -> None:
            with self.lock:
                self.state["message"] = message
                if current is not None:
                    self.state["current"] = current
                if total is not None:
                    self.state["total"] = total
                self.state["updated_at"] = utc_now()

        def run() -> None:
            try:
                result = work(report)
                with self.lock:
                    self.state = {
                        **self.state, "status": "done", "result": result, "message": "Gotowe",
                        "updated_at": utc_now(),
                    }
            except Exception as exc:
                with self.lock:
                    self.state = {
                        **self.state, "status": "error", "message": str(exc), "updated_at": utc_now(),
                    }

        self.executor.submit(run)

    def current(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.state)


class JobService:
    def __init__(
        self,
        store: Store,
        source: RocketJobsSource | None = None,
        evaluator: CodexEvaluator | None = None,
        evaluation_workers: int = 2,
    ):
        self.store = store
        self.sources = [source] if source is not None else [RocketJobsSource(), JustJoinSource()]
        self.source = self.sources[0]
        self.evaluator = evaluator or CodexEvaluator()
        self.evaluation_workers = max(1, min(evaluation_workers, 4))
        self.operations = OperationRunner()

    def sync(self, report: Callable[..., None]) -> dict[str, int]:
        profile = self.store.get_setting("search_profile")
        candidate = self.store.get_setting("candidate_profile")
        counts = {"seen": 0, "matched": 0, "new": 0, "changed": 0, "unchanged": 0, "skipped": 0}

        for source in self.sources:
            name = "RocketJobs" if isinstance(source, RocketJobsSource) else "JustJoinIT"

            def progress(current: int, total: int) -> None:
                report(f"{name}: {current}/{total}", current, total)

            for offer in source.offers(progress=progress):
                counts["seen"] += 1
                matches, _reason = prefilter(offer, profile, candidate)
                if not matches:
                    counts["skipped"] += 1
                    continue
                counts["matched"] += 1
                outcome = self.store.upsert_offer(offer)
                counts[outcome] += 1
        return counts

    def import_url(self, url: str) -> tuple[dict[str, Any], str]:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Wklej bezpośredni link HTTPS do oferty")
        if parsed.netloc == "rocketjobs.pl" and parsed.path.startswith("/oferta-pracy/"):
            source = next((item for item in self.sources if isinstance(item, RocketJobsSource)), RocketJobsSource())
            parser = parse_rocketjobs_page
        elif parsed.netloc == "justjoin.it" and parsed.path.startswith("/job-offer/"):
            source = next((item for item in self.sources if isinstance(item, JustJoinSource)), JustJoinSource())
            parser = parse_justjoin_page
        else:
            raise ValueError("Obsługiwane są linki ofert RocketJobs i JustJoinIT")
        page = source._get(url)
        offer = parser(url, page)
        _, reason = prefilter(
            offer,
            self.store.get_setting("search_profile"),
            self.store.get_setting("candidate_profile"),
        )
        self.store.upsert_offer(offer)
        return self.store.get_offer(self._id_for_url(url)), reason

    @staticmethod
    def _id_for_url(url: str) -> str:
        import hashlib

        return hashlib.sha256(url.encode()).hexdigest()[:24]

    def evaluate(self, ids: list[str], report: Callable[..., None]) -> dict[str, Any]:
        profile = self.store.get_setting("search_profile")
        candidate = self.store.get_setting("candidate_profile")
        profile_hash = stable_hash(profile)
        candidate_hash = stable_hash(candidate)
        total = len(ids)
        offers: list[tuple[int, str, dict[str, Any]]] = []
        errors_by_index: dict[int, dict[str, str]] = {}
        for index, offer_id in enumerate(ids):
            offer = self.store.get_offer(offer_id)
            if not offer:
                errors_by_index[index] = {"id": offer_id, "error": "Offer not found"}
            else:
                offers.append((index, offer_id, offer))

        completed_ids: set[str] = set()
        finished = len(errors_by_index)
        worker_count = min(self.evaluation_workers, len(offers))
        report(
            f"Ukończono {finished}/{total}. Analizuję do {worker_count} ofert równolegle…",
            finished,
            total,
        )

        def evaluate_one(offer_id: str, offer: dict[str, Any]) -> None:
            remote_ok, remote_reason = assess_remote_requirement(offer, profile, candidate)
            if remote_ok:
                result = self.evaluator.evaluate(offer, profile, candidate)
                evaluator_name = self.evaluator.name
            else:
                result = remote_rejection_result(remote_reason)
                evaluator_name = "remote-validation"
            self.store.save_evaluation(
                offer_id, result, evaluator_name,
                profile_hash=profile_hash, candidate_hash=candidate_hash,
                offer_hash=offer["content_hash"],
            )

        with ThreadPoolExecutor(max_workers=max(1, worker_count), thread_name_prefix="offer-evaluation") as executor:
            futures = {
                executor.submit(evaluate_one, offer_id, offer): (index, offer_id)
                for index, offer_id, offer in offers
            }
            for future in as_completed(futures):
                index, offer_id = futures[future]
                finished += 1
                try:
                    future.result()
                    completed_ids.add(offer_id)
                except Exception as exc:
                    errors_by_index[index] = {"id": offer_id, "error": str(exc)}
                message = (
                    f"Ukończono {finished}/{total}. Analizuję kolejne oferty…"
                    if finished < total else f"Ukończono {finished}/{total}."
                )
                report(message, finished, total)

        completed = [offer_id for offer_id in ids if offer_id in completed_ids]
        errors = [errors_by_index[index] for index in sorted(errors_by_index)]
        return {"completed": completed, "errors": errors}
