from __future__ import annotations

import argparse
import json

from .api import create_app
from .mcp_server import create_mcp_server
from .service import JobService
from .store import Store
from .config import data_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Lokalny asystent poszukiwania pracy")
    parser.add_argument("--web", action="store_true", help="Uruchom panel na 127.0.0.1:5757 do pracy developerskiej")
    parser.add_argument("--mcp", action="store_true", help="Uruchom serwer MCP przez stdio dla Codex")
    parser.add_argument("--sync", action="store_true", help="Pobierz pasujące oferty ze wszystkich źródeł i zakończ")
    args = parser.parse_args()
    if args.mcp:
        create_mcp_server().run(transport="stdio")
        return
    if args.sync:
        service = JobService(Store(data_dir() / "getmeajob.sqlite3"))
        result = service.sync(lambda message, *_: print(message))
        print(json.dumps(result, ensure_ascii=False))
        return
    app = create_app()
    if args.web:
        app.run(host="127.0.0.1", port=5757, debug=False, use_reloader=False)
        return
    import webview

    webview.create_window("GetMeAJob", app, width=1340, height=860, min_size=(1000, 680))
    webview.start()


if __name__ == "__main__":
    main()
