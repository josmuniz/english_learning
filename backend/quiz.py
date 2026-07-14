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


def expected_answer(word: dict, qtype: str, direction: str) -> tuple:
    if qtype == "cloze":
        return word["word_en"], ""
    if qtype == "mc_phrase":
        if direction == "en_to_es":
            return word["example_es"], ""
        return word["example_en"], ""
    if direction == "es_to_en":
        return word["word_en"], word.get("synonym_en", "")
    return word["word_es"], word.get("synonym_es", "")


def _has_examples(w: dict) -> bool:
    return bool(w.get("example_en")) and bool(w.get("example_es"))


def eligible_types(word: dict, all_words: list, requested: list) -> list:
    n = len(all_words)
    out = []
    for t in requested:
        if t == "typing":
            out.append(t)
        elif n < 4:
            continue
        elif t == "mc_word":
            out.append(t)
        elif t == "cloze":
            if word.get("example_en") and word["word_en"].lower() in word["example_en"].lower():
                out.append(t)
        elif t == "mc_phrase":
            if _has_examples(word):
                donors = [w for w in all_words if w["id"] != word["id"] and _has_examples(w)]
                if len(donors) >= 3:
                    out.append(t)
    return out


def choose_type(word: dict, all_words: list, requested: list, rng=random) -> str:
    elig = eligible_types(word, all_words, requested)
    if elig:
        return rng.choice(elig)
    return "mc_word" if len(all_words) >= 4 else "typing"
