import pytest
from fastapi.testclient import TestClient


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

    async def fake_translate(text, client, src="en", tgt="es"):
        return f"tr({text})"

    async def fake_dictionary(word, client):
        return {"word_en": word, "type": "noun", "ipa": "/tɛst/",
                "definition_en": "def", "example_en": f"An example with {word}.",
                "synonym_raw": "", "antonym_raw": ""}

    async def fake_datamuse(word, rel, client):
        return ""

    monkeypatch.setattr(main, "translate", fake_translate)
    monkeypatch.setattr(main, "fetch_dictionary", fake_dictionary)
    monkeypatch.setattr(main, "datamuse_word", fake_datamuse)


@pytest.fixture
def word_id(client, mock_apis):
    return client.post("/api/words", json={"word": "strong"}).json()["id"]


@pytest.fixture
def phrase_id(client, mock_apis):
    return client.post("/api/words", json={"word": "break the ice"}).json()["id"]


def test_patch_updates_editable_fields(client, word_id):
    r = client.patch(f"/api/words/{word_id}", json={
        "pronunciation_es": "strong",
        "synonym_en": "powerful", "synonym_es": "poderoso",
        "antonym_en": "weak", "antonym_es": "débil",
        "example_en": "He is strong.", "example_es": "Él es fuerte.",
        "ipa": "/strɒŋ/",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["pronunciation_es"] == "strong"
    assert d["synonym_en"] == "powerful"
    assert d["antonym_es"] == "débil"
    assert d["example_en"] == "He is strong."
    assert d["ipa"] == "/strɒŋ/"
    # persistió en disco
    stored = next(w for w in client.get("/api/words").json() if w["id"] == word_id)
    assert stored["pronunciation_es"] == "strong"


def test_patch_partial_only_touches_sent_fields(client, phrase_id):
    r = client.patch(f"/api/words/{phrase_id}", json={"pronunciation_es": "breik de ais"})
    assert r.status_code == 200
    d = r.json()
    assert d["pronunciation_es"] == "breik de ais"
    assert d["synonym_en"] == ""          # no tocado
    assert d["word_en"] == "break the ice"  # no tocado


def test_patch_strips_whitespace(client, word_id):
    r = client.patch(f"/api/words/{word_id}", json={"pronunciation_es": "  strong  "})
    assert r.status_code == 200
    assert r.json()["pronunciation_es"] == "strong"


def test_patch_ignores_protected_fields(client, word_id):
    r = client.patch(f"/api/words/{word_id}",
                     json={"times_practiced": 99, "word_en": "hacked",
                           "pronunciation_es": "ok"})
    assert r.status_code == 200
    d = r.json()
    assert d["times_practiced"] == 0
    assert d["word_en"] == "strong"
    assert d["pronunciation_es"] == "ok"


def test_patch_404_unknown_id(client):
    assert client.patch("/api/words/no-existe", json={"ipa": "x"}).status_code == 404


@pytest.mark.parametrize("field", ["example_en", "example_es"])
def test_patch_example_over_10_words_422(client, word_id, field):
    long_example = "one two three four five six seven eight nine ten eleven"
    r = client.patch(f"/api/words/{word_id}", json={field: long_example})
    assert r.status_code == 422
    assert r.json()["detail"] == "El ejemplo no puede superar 10 palabras"


@pytest.mark.parametrize("field", ["example_en", "example_es"])
def test_patch_example_exactly_10_words_ok(client, word_id, field):
    ten = "one two three four five six seven eight nine ten"
    r = client.patch(f"/api/words/{word_id}", json={field: ten})
    assert r.status_code == 200
    assert r.json()[field] == ten
