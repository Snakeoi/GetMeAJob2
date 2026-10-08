from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("GETMEAJOB_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / "GetMeAJob"


DEFAULT_SEARCH_PROFILE = {
    "roles": ["Python Developer", "Full Stack Developer z Vue"],
    "remote_only": True,
    "contract_types": ["UoP", "B2B"],
    "minimum_uop_gross_pln_month": 20000,
    "minimum_b2b_net_pln_month": 20000,
    "include_unknown_salary": True,
    "excluded_terms": [],
}

DEFAULT_DECISION_PROFILE = {
    "approve_min_score": 70,
    "reject_below_score": 50,
}


DEFAULT_CANDIDATE_PROFILE = {
    "headline": "Python Developer / Full Stack Developer",
    "summary": "Komercyjny rozwój aplikacji webowych od 2019 roku, głównie Python/Flask i Vue.js.",
    "facts": [
        {
            "id": "nordea-backend",
            "text": "Nordea (od 2024): budowa i rozwój aplikacji Flask, REST, Flask-SQLAlchemy, Flask-Marshmallow i Pandas.",
        },
        {
            "id": "nordea-frontend",
            "text": "Nordea: tworzenie aplikacji SPA w Vue.js i Angular.js.",
        },
        {
            "id": "nordea-ownership",
            "text": "Nordea: code review, testowanie i scalanie zmian, wdrożenia, dokumentacja oraz wpływ na roadmapę produktu.",
        },
        {
            "id": "nordea-copilot",
            "text": "Nordea: używanie GitHub Copilot w pracy programistycznej.",
        },
        {
            "id": "nordea-data",
            "text": "Nordea: ETL oraz analiza baz MariaDB i PostgreSQL; zarządzanie serwerami Red Hat i Apache.",
        },
        {
            "id": "automatykon-fullstack",
            "text": "Automatykon (2023-2024): samodzielna aplikacja Flask i Vue.js dla sterownika fermy, z SQLite, Redis, Chart.js i obsługą wielu języków.",
        },
        {
            "id": "otinus-integrations",
            "text": "Otinus (2019-2023): aplikacje Python/Flask, PHP i JavaScript, integracje REST z WooCommerce, OLX i innymi platformami oraz web scraping.",
        },
        {
            "id": "otinus-leadership",
            "text": "Otinus: prowadzenie czteroosobowego zespołu IT i marketingu oraz odpowiedzialność za aplikacje, strony i bazy danych.",
        },
        {
            "id": "listed-tools",
            "text": "CV wymienia GIT, GitHub, Bitbucket i Docker wśród używanych narzędzi; nie opisuje szczegółowo sposobu użycia Dockera w projektach.",
        },
        {
            "id": "languages",
            "text": "Języki: polski ojczysty, angielski B2/C1.",
        },
        {
            "id": "location-bydgoszcz",
            "kind": "location",
            "city": "Bydgoszcz",
            "country": "Polska",
            "text": "CV podaje lokalizację kandydata: Bydgoszcz, Polska.",
        },
    ],
}
