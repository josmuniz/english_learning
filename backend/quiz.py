"""Motor de quiz: puro, sin I/O. Consumido por main.py y por los tests."""
import random
import re
import unicodedata

ALL_TYPES = ["mc_word", "mc_phrase", "cloze", "typing", "mc_image"]

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
        elif t == "mc_image":
            if word.get("image_status", "none") == "approved":
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


def pick_distractors(word: dict, all_words: list, rng=random, need_example: bool = False) -> list:
    pool = [w for w in all_words if w["id"] != word["id"]]
    if need_example:
        pool = [w for w in pool if _has_examples(w)]
    return rng.sample(pool, 3)


def build_question(word: dict, qtype: str, direction: str, all_words: list, rng=random) -> dict:
    if qtype in ("cloze", "mc_image"):
        resolved = "es_to_en"          # la respuesta es la palabra en inglés
    elif direction == "both":
        resolved = rng.choice(["es_to_en", "en_to_es"])
    else:
        resolved = direction

    q = {
        "word_id": word["id"],
        "type": qtype,
        "direction": resolved,
        "hint": word.get("type", "word"),
        "prompt_secondary": "",
    }

    if qtype == "typing":
        q["prompt"] = word["word_es"] if resolved == "es_to_en" else word["word_en"]
        if resolved == "en_to_es" and word.get("pronunciation_es"):
            q["prompt_secondary"] = f'({word["pronunciation_es"]})'
        return _attach_image(q, word)

    if qtype == "mc_word":
        distractors = pick_distractors(word, all_words, rng)
        if resolved == "en_to_es":
            q["prompt"] = word["word_en"]
            if word.get("pronunciation_es"):
                q["prompt_secondary"] = f'({word["pronunciation_es"]})'
            opts = [word["word_es"]] + [d["word_es"] for d in distractors]
        else:
            q["prompt"] = word["word_es"]
            opts = [word["word_en"]] + [d["word_en"] for d in distractors]
    elif qtype == "mc_image":
        distractors = pick_distractors(word, all_words, rng)
        q["prompt"] = "Observa la escena"
        opts = [word["word_en"]] + [d["word_en"] for d in distractors]
    elif qtype == "mc_phrase":
        distractors = pick_distractors(word, all_words, rng, need_example=True)
        if resolved == "en_to_es":
            q["prompt"] = word["example_en"]
            opts = [word["example_es"]] + [d["example_es"] for d in distractors]
        else:
            q["prompt"] = word["example_es"]
            opts = [word["example_en"]] + [d["example_en"] for d in distractors]
    else:  # cloze
        distractors = pick_distractors(word, all_words, rng)
        pattern = re.compile(re.escape(word["word_en"]), re.IGNORECASE)
        q["prompt"] = pattern.sub("____", word["example_en"], count=1)
        opts = [word["word_en"]] + [d["word_en"] for d in distractors]

    rng.shuffle(opts)
    q["options"] = opts
    return _attach_image(q, word)


def _attach_image(q: dict, word: dict) -> dict:
    if word.get("image_status", "none") == "approved" and word.get("image"):
        q["image_url"] = f"/{word['image']}"
    return q
