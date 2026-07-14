import json
import random

import pytest

from backend import quiz


def make_word(i, **over):
    w = {
        "id": f"id-{i}",
        "created_at": "2026-07-14T00:00:00",
        "word_en": f"word{i}",
        "word_es": f"palabra{i}",
        "type": "noun",
        "ipa": "",
        "pronunciation_es": f"pron{i}",
        "synonym_en": "",
        "synonym_es": "",
        "antonym_en": "",
        "antonym_es": "",
        "definition_en": "",
        "definition_es": "",
        "example_en": f"This is word{i} in a sentence.",
        "example_es": f"Esta es palabra{i} en una frase.",
        "times_practiced": 0,
        "times_correct": 0,
    }
    w.update(over)
    return w


# ── normalize / is_match ─────────────────────────────────────────────

def test_normalize_strips_accents_case_and_articles():
    assert quiz.normalize("  El Fuerte ") == "fuerte"
    assert quiz.normalize("canción") == "cancion"
    assert quiz.normalize("The   House") == "house"
    assert quiz.normalize("una manzana roja") == "manzana roja"


def test_is_match_tolerant():
    assert quiz.is_match("La PALABRA1", "palabra1")
    assert quiz.is_match(" fuerte. ".replace(".", ""), "El Fuerte")
    assert not quiz.is_match("debil", "fuerte")


def test_is_match_accepts_synonym():
    assert quiz.is_match("exquisite", "beautiful", "exquisite")
    assert not quiz.is_match("ugly", "beautiful", "exquisite")
    assert not quiz.is_match("", "beautiful", "")


# ── ponderación ──────────────────────────────────────────────────────

def test_weight_new_word_is_3():
    assert quiz.word_weight(make_word(1)) == 3.0


def test_weight_scales_with_failure_rate():
    assert quiz.word_weight(make_word(1, times_practiced=4, times_correct=4)) == 1.0
    assert quiz.word_weight(make_word(1, times_practiced=4, times_correct=0)) == 5.0
    assert quiz.word_weight(make_word(1, times_practiced=4, times_correct=2)) == 3.0


def test_pick_word_prefers_failing_words():
    words = [
        make_word(1, times_practiced=10, times_correct=10),  # peso 1
        make_word(2, times_practiced=10, times_correct=0),   # peso 5
    ]
    rng = random.Random(42)
    picks = [quiz.pick_word(words, rng)["id"] for _ in range(500)]
    assert picks.count("id-2") > picks.count("id-1") * 2


# ── expected_answer ──────────────────────────────────────────────────

def test_expected_answer_by_type_and_direction():
    w = make_word(1, synonym_en="syn-en", synonym_es="syn-es")
    assert quiz.expected_answer(w, "mc_word", "es_to_en") == ("word1", "syn-en")
    assert quiz.expected_answer(w, "typing", "en_to_es") == ("palabra1", "syn-es")
    assert quiz.expected_answer(w, "cloze", "en_to_es") == ("word1", "")
    assert quiz.expected_answer(w, "mc_phrase", "en_to_es") == (
        "Esta es palabra1 en una frase.", "")
    assert quiz.expected_answer(w, "mc_phrase", "es_to_en") == (
        "This is word1 in a sentence.", "")


# ── elegibilidad ─────────────────────────────────────────────────────

def test_word_without_example_never_gets_phrase_or_cloze():
    words = [make_word(i) for i in range(1, 6)]
    words[0]["example_en"] = ""
    words[0]["example_es"] = ""
    for _ in range(50):
        t = quiz.choose_type(words[0], words, ["mc_phrase", "cloze"], random)
        assert t == "mc_word"  # fallback del spec §5.2


def test_cloze_requires_word_present_in_example():
    words = [make_word(i) for i in range(1, 6)]
    words[0]["example_en"] = "A sentence without the target."
    assert "cloze" not in quiz.eligible_types(words[0], words, ["cloze"])


def test_small_vocab_degrades_to_typing():
    words = [make_word(i) for i in range(1, 4)]  # solo 3 palabras
    assert quiz.eligible_types(words[0], words, ["mc_word"]) == []
    assert quiz.choose_type(words[0], words, ["mc_word"], random) == "typing"


# ── build_question ───────────────────────────────────────────────────

def test_mc_word_has_4_unique_options_including_answer():
    words = [make_word(i) for i in range(1, 6)]
    q = quiz.build_question(words[0], "mc_word", "en_to_es", words, random.Random(1))
    assert q["type"] == "mc_word"
    assert q["direction"] == "en_to_es"
    assert q["prompt"] == "word1"
    assert q["prompt_secondary"] == "(pron1)"
    assert len(q["options"]) == 4 == len(set(q["options"]))
    assert "palabra1" in q["options"]
    assert "correct" not in q and "correct_answer" not in q


def test_cloze_hides_word_and_ignores_direction():
    words = [make_word(i) for i in range(1, 6)]
    q = quiz.build_question(words[0], "cloze", "en_to_es", words, random.Random(1))
    assert "____" in q["prompt"]
    assert "word1" not in q["prompt"].lower()
    assert "word1" in q["options"]
    assert q["direction"] == "es_to_en"


def test_mc_phrase_respects_direction():
    words = [make_word(i) for i in range(1, 6)]
    q = quiz.build_question(words[0], "mc_phrase", "es_to_en", words, random.Random(1))
    assert q["prompt"] == "Esta es palabra1 en una frase."
    assert "This is word1 in a sentence." in q["options"]


def test_typing_has_no_options():
    words = [make_word(i) for i in range(1, 6)]
    q = quiz.build_question(words[0], "typing", "es_to_en", words, random.Random(1))
    assert q["prompt"] == "palabra1"
    assert "options" not in q


def test_both_resolves_to_concrete_direction():
    words = [make_word(i) for i in range(1, 6)]
    q = quiz.build_question(words[0], "mc_word", "both", words, random.Random(1))
    assert q["direction"] in ("es_to_en", "en_to_es")
