import pytest

from getmeajob.description_language import description_language
from getmeajob.store import Store
from tests.test_store_api import OFFER


POLISH = "Szukamy programisty do naszego zespołu. Oferujemy rozwój oraz pracę z Python i Vue. Wymagana znajomość języka angielskiego."
ENGLISH = "We are looking for a developer to join our team. You will work with Python and Vue. Polish language is required."


@pytest.mark.parametrize(("text", "expected"), [
    (POLISH, "pl"),
    (ENGLISH, "en"),
    (POLISH + " " + ENGLISH, "mixed"),
    (f"<p>{POLISH}</p><ul><li>Python</li><li>SQL</li></ul>", "pl"),
    ("Python SQL Django Vue English B2", "unknown"),
    ("", "unknown"),
    ("the " * 20, "unknown"),
    ("Wir suchen einen Entwickler mit guten Deutschkenntnissen.", "unknown"),
])
def test_language_hint(text, expected):
    assert description_language(text) == expected


def test_language_available_for_existing_offers_and_changes(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    store.upsert_offer({**OFFER, "description": POLISH})
    offer = store.list_offers()[0]
    assert offer["description_language"] == "pl"
    assert Store(store.path).get_offer(offer["id"])["description_language"] == "pl"
    store.upsert_offer({**OFFER, "description": ENGLISH})
    assert store.get_offer(offer["id"])["description_language"] == "en"
