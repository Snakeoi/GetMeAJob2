from __future__ import annotations

import re
import unicodedata
from typing import Any


WORK_MODES = {"remote", "hybrid", "onsite"}
CONTRACT_TYPES = {"UoP", "B2B"}


def normalize(text: str) -> str:
    value = "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))
    value = re.sub(r"full[\s-]?stack", "full stack", value)
    value = re.sub(r"\b(?:engineer|programista|programistka|inzynier|inzynierka)\b", "developer", value)
    return " ".join(re.findall(r"[\w]+", value))


def role_parts(role: str) -> tuple[str, str]:
    parts = re.split(r"\s+(?:z|with)\s+", role.strip(), maxsplit=1, flags=re.I)
    return parts[0], parts[1] if len(parts) == 2 else ""


def title_matches_role(title: str, description: str, role: str) -> bool:
    position, qualifier = role_parts(role)
    title_words = set(normalize(title).split())
    role_words = set(normalize(position).split())
    if not role_words or not role_words <= title_words:
        return False
    if qualifier and not set(normalize(qualifier).split()) <= set(normalize(title + " " + description).split()):
        return False
    unwanted = {"qa", "test", "testing", "automation", "devops"}
    if (title_words & unwanted) - role_words:
        return False
    return True


def title_matches_roles(title: str, description: str, roles: list[str]) -> bool:
    title_words = set(normalize(title).split())
    if {"full", "stack"} <= title_words:
        full_stack_roles = [role for role in roles if {"full", "stack"} <= set(normalize(role_parts(role)[0]).split())]
        if full_stack_roles:
            roles = full_stack_roles
    return any(title_matches_role(title, description, role) for role in roles)


def slug_matches_roles(slug: str, roles: list[str]) -> bool:
    slug_text = normalize(slug).replace(" ", "")
    for role in roles:
        position, _ = role_parts(role)
        words = [word for word in normalize(position).split() if word not in {"developer", "specialist", "specjalista"}]
        if not words:
            words = normalize(position).split()
        if words and all(word in slug_text for word in words):
            return True
    return False


def search_terms(roles: list[str]) -> list[str]:
    return list(dict.fromkeys(role.strip().lower() for role in roles if role.strip()))


def validate_search_profile(profile: dict[str, Any]) -> dict[str, Any]:
    roles = profile.get("roles")
    if not isinstance(roles, list) or not roles or any(not isinstance(role, str) or not role.strip() for role in roles):
        raise ValueError("Podaj co najmniej jedno stanowisko")
    profile["roles"] = list(dict.fromkeys(role.strip() for role in roles))

    modes = profile.get("work_modes")
    if not isinstance(modes, list) or not modes or not set(modes) <= WORK_MODES:
        raise ValueError("Wybierz co najmniej jeden tryb pracy")
    profile["work_modes"] = list(dict.fromkeys(modes))

    locations = profile.get("work_locations")
    if not isinstance(locations, list) or any(not isinstance(city, str) or not city.strip() for city in locations):
        raise ValueError("Podaj prawidłowe lokalizacje pracy")
    profile["work_locations"] = list(dict.fromkeys(city.strip() for city in locations))
    if set(modes) & {"hybrid", "onsite"} and not profile["work_locations"]:
        raise ValueError("Dla pracy hybrydowej lub stacjonarnej podaj lokalizację")

    contracts = profile.get("contract_types")
    if not isinstance(contracts, list) or not contracts or not set(contracts) <= CONTRACT_TYPES:
        raise ValueError("Wybierz co najmniej jedną formę zatrudnienia")
    profile["contract_types"] = list(dict.fromkeys(contracts))

    for key in ("minimum_uop_gross_pln_month", "minimum_b2b_net_pln_month"):
        value = profile.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError("Minimalne wynagrodzenie musi być liczbą nieujemną")
    if not isinstance(profile.get("include_unknown_salary"), bool):
        raise ValueError("Nieprawidłowe ustawienie ofert bez widełek")
    excluded = profile.get("excluded_terms")
    if not isinstance(excluded, list) or any(not isinstance(term, str) for term in excluded):
        raise ValueError("Wykluczone frazy muszą być listą tekstów")
    return profile
