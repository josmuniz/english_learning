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
