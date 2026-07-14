"""Motor de quiz: puro, sin I/O. Consumido por main.py y por los tests."""
import random
import re
import unicodedata

ALL_TYPES = ["mc_word", "mc_phrase", "cloze", "typing"]

_ARTICLES = re.compile(r"^(el|la|los|las|un|una|unos|unas|the|a|an)\s+", re.IGNORECASE)


def normalize(text: str) -> str:
    s = text.strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _ARTICLES.sub("", s)
    s = re.sub(r"\s+", " ", s)
    return s


def is_match(answer: str, expected: str, synonym: str = "") -> bool:
    a = normalize(answer)
    if not a:
        return False
    if a == normalize(expected):
        return True
    return bool(synonym.strip()) and a == normalize(synonym)


def word_weight(w: dict) -> float:
    tp = w.get("times_practiced", 0)
    if tp == 0:
        return 3.0
    return 1.0 + 4.0 * (1 - w.get("times_correct", 0) / tp)


def pick_word(words: list, rng=random) -> dict:
    weights = [word_weight(w) for w in words]
    return rng.choices(words, weights=weights, k=1)[0]
