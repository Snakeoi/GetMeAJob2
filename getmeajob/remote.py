from __future__ import annotations

import re
import unicodedata
from typing import Any


REMOTE_CONTRADICTIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bhybrid(?:\s+by\s+design)?\b|\bhybryd\w*\b", re.I),
    re.compile(r"\bon[\s-]?site\b|\bstacjonarn\w*\b", re.I),
    re.compile(
        r"\b(?:office|biur\w*)\s+(?:attendance|presence|required|requirement|visit\w*|days?)\b"
        r"|\b(?:attendance|presence|visit\w*|work(?:ing)?)\s+(?:at|in|from|to)\s+(?:(?:the|our|an)\s+)?office\b"
        r"|\b(?:obecno\w*|wizyt\w*|prac\w*)\s+w\s+(?:nasz\w+\s+)?biur\w*\b",
        re.I,
    ),
    re.compile(
        r"\b(?:at\s+least\s+)?\d+\s+days?\s+(?:a|per)\s+(?:week|month)\s+(?:at|in|from)\s+(?:the\s+)?office\b"
        r"|\b(?:co\s+najmniej\s+)?\d+\s+dni\w*\s+(?:w\s+tygodniu|w\s+miesi[aą]cu)\s+w\s+biur\w*\b",
        re.I,
    ),
)

def _normalized(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def candidate_work_locations(candidate: dict[str, Any] | None) -> set[str]:
    """Return work locations explicitly stored as verified CV facts."""
    locations: set[str] = set()
    for fact in (candidate or {}).get("facts", []):
        if fact.get("kind") != "location":
            continue
        city = str(fact.get("city") or "").strip()
        if city:
            locations.add(city)
    return locations


def offer_matches_candidate_location(offer: dict[str, Any], candidate: dict[str, Any] | None) -> bool:
    offer_location = _normalized(str(offer.get("location") or ""))
    if not offer_location:
        return False
    return any(
        re.search(rf"(?<!\w){re.escape(_normalized(city))}(?!\w)", offer_location)
        for city in candidate_work_locations(candidate)
    )


def assess_remote_requirement(
    offer: dict[str, Any], profile: dict[str, Any], candidate: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Accept remote work, or any work mode in a location verified by the CV."""
    if "work_modes" in profile:
        modes = set(profile["work_modes"])
        description = " ".join(str(offer.get("description") or "").split())
        mode = offer.get("remote_mode")
        if mode == "remote" and any(pattern.search(description) for pattern in REMOTE_CONTRADICTIONS):
            mode = "hybrid" if re.search(r"hybrid|hybryd", description, re.I) else "onsite"
        if mode not in modes:
            return False, "Tryb pracy nie należy do wybranych"
        if mode in {"hybrid", "onsite"}:
            allowed = {str(city).strip() for city in profile.get("work_locations", []) if str(city).strip()}
            offer_location = _normalized(str(offer.get("location") or ""))
            if not allowed or not any(re.search(rf"(?<!\w){re.escape(_normalized(city))}(?!\w)", offer_location) for city in allowed):
                return False, "Oferta jest poza wybranymi lokalizacjami pracy"
        return True, ""
    if not profile.get("remote_only"):
        return True, ""

    if offer_matches_candidate_location(offer, candidate):
        return True, ""

    description = " ".join(str(offer.get("description") or "").split())
    if any(pattern.search(description) for pattern in REMOTE_CONTRADICTIONS):
        schedule = re.search(r"\b(\d+)\s+onsite\s*/\s*(\d+)\s+remote\b", description, re.I)
        if schedule:
            onsite_days, remote_days = schedule.groups()
            return False, (
                "Oferta wymaga pracy hybrydowej: "
                f"{onsite_days} {'dzień' if onsite_days == '1' else 'dni'} onsite / "
                f"{remote_days} {'dzień' if remote_days == '1' else 'dni'} zdalnie"
            )
        return False, "Opis oferty wskazuje tryb hybrydowy, stacjonarny lub wymaganą obecność w biurze"
    if offer.get("remote_mode") != "remote":
        return False, "Oferta nie potwierdza pracy w pełni zdalnej"
    return True, ""


def remote_rejection_result(reason: str) -> dict[str, Any]:
    return {
        "recommendation": "pomiń",
        "score": 0,
        "confidence": "wysoka",
        "rationale": f"Oferta nie spełnia ustawionych warunków trybu lub lokalizacji pracy. {reason}.",
        "requirements": [reason],
        "matches": [],
        "gaps": [reason],
        "unknowns": [],
    }
