from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import data_dir
from .store import Store


def create_mcp_server(storage_path: Path | None = None) -> FastMCP:
    store = Store(storage_path or data_dir() / "getmeajob.sqlite3")
    server = FastMCP("GetMeAJob")

    @server.tool()
    def list_offers() -> str:
        """List saved job offers and their evaluations for the local owner."""
        return json.dumps(store.list_offers(), ensure_ascii=False)

    @server.tool()
    def get_offer(offer_id: str) -> str:
        """Read one saved job offer and its latest evaluation."""
        return json.dumps(store.get_offer(offer_id), ensure_ascii=False)

    @server.tool()
    def get_candidate_profile() -> str:
        """Read verified candidate facts extracted from the owner's CV."""
        return json.dumps(store.get_setting("candidate_profile"), ensure_ascii=False)

    @server.tool()
    def get_search_profile() -> str:
        """Read the owner's desired roles, remote work and salary thresholds."""
        return json.dumps(store.get_setting("search_profile"), ensure_ascii=False)

    @server.tool()
    def get_approved_applications() -> str:
        """Read only applications the owner approved in the desktop app. Includes the local CV path."""
        approved = [item for item in store.applications() if item["status"] == "approved"]
        result = [
            {
                "application": item,
                "offer": store.get_offer(item["offer_id"]),
                "resume_path": store.get_setting("resume_path"),
            }
            for item in approved
        ]
        return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def mark_application_submitted(offer_id: str, confirmation: str, notes: str = "") -> str:
        """Record a real submission only after the recruitment site confirms it; the offer must already be owner-approved."""
        store.mark_submitted(offer_id, confirmation, notes)
        return json.dumps({"ok": True, "offer_id": offer_id}, ensure_ascii=False)

    return server
