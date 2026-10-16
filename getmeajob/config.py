from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("GETMEAJOB_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / "GetMeAJob"


DEFAULT_SEARCH_PROFILE = {
    "roles": [],
    "work_modes": ["remote"],
    "work_locations": [],
    "contract_types": ["UoP", "B2B"],
    "minimum_uop_gross_pln_month": 0,
    "minimum_b2b_net_pln_month": 0,
    "include_unknown_salary": True,
    "excluded_terms": [],
}

DEFAULT_DECISION_PROFILE = {
    "approve_min_score": 70,
    "reject_below_score": 50,
}


DEFAULT_CANDIDATE_PROFILE = {
    "headline": "",
    "summary": "",
    "facts": [],
}
