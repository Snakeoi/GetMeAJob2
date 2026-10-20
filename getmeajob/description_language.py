"""Conservative local hints about the language of the original description."""

import re
import unicodedata
from functools import lru_cache
from html import unescape


# Prose markers, rather than technology names or required language skills.
_POLISH = set("""
    i w z na do oraz jest sie dla ze od lub przez jako przy nas
    bedziesz twoje twoich naszym naszego szukamy oferujemy wymagania
    obowiazki doswiadczenie znajomosc praca pracy zespolu rozwoj
    tworzenie utrzymanie umiejetnosc wspolpraca wynagrodzenie
""".split())
_ENGLISH = set("""
    the and with for you your we our are is will have to of in
    as from this that an be or us work working team experience
    requirements responsibilities looking offer develop building
""".split())


@lru_cache(maxsize=2048)
def description_language(description: str) -> str:
    """Return pl/en/mixed/unknown; short or unsupported prose stays unknown."""
    text = unescape(re.sub(r"<[^>]*>", " ", description or ""))
    text = unicodedata.normalize("NFKD", text.lower().replace("ł", "l"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    words = re.findall(r"[^\W\d_]+", text)
    polish = [word for word in words if word in _POLISH]
    english = [word for word in words if word in _ENGLISH]
    pl_supported = len(polish) >= 4 and len(set(polish)) >= 3
    en_supported = len(english) >= 4 and len(set(english)) >= 3
    if pl_supported and en_supported and min(len(polish), len(english)) / max(len(polish), len(english)) >= 0.4:
        return "mixed"
    if pl_supported and len(polish) >= 2 * len(english):
        return "pl"
    if en_supported and len(english) >= 2 * len(polish):
        return "en"
    return "unknown"
