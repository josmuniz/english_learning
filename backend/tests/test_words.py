import pytest
from fastapi.testclient import TestClient

from backend import quiz
from backend.tests.test_quiz import make_word


@pytest.fixture
def client(tmp_path, monkeypatch):
    import backend.main as main
    data_file = tmp_path / "words.json"
    data_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "DATA_FILE", data_file)
    return TestClient(main.app)


@pytest.fixture
def mock_apis(monkeypatch):
    import backend.main as main
    calls = {"dictionary": 0}

    async def fake_translate(text, client, src="en", tgt="es"):
        return f"tr({text})"

    async def fake_dictionary(word, client):
        calls["dictionary"] += 1
        return {"word_en": word, "type": "noun", "ipa": "",
                "definition_en": "def", "example_en": f"An example with {word}.",
                "synonym_raw": "", "antonym_raw": ""}

    async def fake_datamuse(word, rel, client):
        return ""

    monkeypatch.setattr(main, "translate", fake_translate)
    monkeypatch.setattr(main, "fetch_dictionary", fake_dictionary)
    monkeypatch.setattr(main, "datamuse_word", fake_datamuse)
    return calls


def test_add_phrase_skips_dictionary(client, mock_apis):
    r = client.post("/api/words", json={"word": "Break The Ice"})
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == "phrase"
    assert d["word_en"] == "break the ice"
    assert d["word_es"] == "tr(break the ice)"
    assert d["example_en"] == "" and d["ipa"] == "" and d["synonym_en"] == ""
    assert mock_apis["dictionary"] == 0


def test_add_phrase_translate_fallback(client, monkeypatch):
    import backend.main as main

    async def empty_translate(text, client, src="en", tgt="es"):
        return ""

    monkeypatch.setattr(main, "translate", empty_translate)
    r = client.post("/api/words", json={"word": "kick the bucket"})
    assert r.status_code == 200
    assert r.json()["word_es"] == "kick the bucket"


def test_add_word_too_long_400(client):
    r = client.post("/api/words", json={"word": "x " * 45})  # 89 chars tras strip
    assert r.status_code == 400


def test_add_phrase_duplicate_409(client, mock_apis):
    assert client.post("/api/words", json={"word": "break the ice"}).status_code == 200
    assert client.post("/api/words", json={"word": "Break The Ice"}).status_code == 409


def test_single_word_still_uses_dictionary(client, mock_apis):
    r = client.post("/api/words", json={"word": "strong"})
    assert r.status_code == 200
    assert r.json()["type"] == "noun"
    assert mock_apis["dictionary"] == 1


def test_phrase_only_eligible_for_mc_word_and_typing():
    phrase = make_word(1, word_en="break the ice", type="phrase",
                       example_en="", example_es="")
    all_words = [phrase] + [make_word(i) for i in range(2, 6)]
    elig = quiz.eligible_types(phrase, all_words, quiz.ALL_TYPES)
    assert set(elig) == {"mc_word", "typing"}


# ── lang: alta bilingüe ──────────────────────────────────────────────

def test_add_spanish_word_enriched_via_english_pipeline(client, mock_apis):
    r = client.post("/api/words", json={"word": "Mariposa", "lang": "es"})
    assert r.status_code == 200
    d = r.json()
    assert d["word_es"] == "mariposa"          # entrada original, no re-traducción
    assert d["word_en"] == "tr(mariposa)"      # traducción ES→EN
    assert d["type"] == "noun"                 # pipeline inglés corrió
    assert mock_apis["dictionary"] == 1        # dictionary llamado con la traducción


def test_add_spanish_phrase_inverted(client, mock_apis):
    r = client.post("/api/words", json={"word": "romper el hielo", "lang": "es"})
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == "phrase"               # traducción multi-palabra → frase
    assert d["word_en"] == "tr(romper el hielo)"
    assert d["word_es"] == "romper el hielo"
    assert mock_apis["dictionary"] == 0


def test_add_spanish_translate_fails_400(client, monkeypatch):
    import backend.main as main

    async def empty_translate(text, client, src="en", tgt="es"):
        return ""

    monkeypatch.setattr(main, "translate", empty_translate)
    r = client.post("/api/words", json={"word": "mariposa", "lang": "es"})
    assert r.status_code == 400


def test_dedup_by_word_es(client, mock_apis):
    assert client.post("/api/words",
                       json={"word": "hola", "lang": "es"}).status_code == 200
    # segunda alta con la misma entrada española → 409 por word_es
    assert client.post("/api/words",
                       json={"word": "Hola", "lang": "es"}).status_code == 409


def test_lang_invalid_422_and_default_en(client, mock_apis):
    assert client.post("/api/words",
                       json={"word": "strong", "lang": "fr"}).status_code == 422
    r = client.post("/api/words", json={"word": "strong"})   # sin lang → EN
    assert r.status_code == 200
    assert mock_apis["dictionary"] == 1
