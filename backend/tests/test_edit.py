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

# ── word_es editable (traducción) ────────────────────────────────────

def test_patch_updates_word_es(client, word_id):
    r = client.patch(f"/api/words/{word_id}", json={"word_es": "fortísimo"})
    assert r.status_code == 200
    assert r.json()["word_es"] == "fortísimo"
    stored = next(w for w in client.get("/api/words").json() if w["id"] == word_id)
    assert stored["word_es"] == "fortísimo"


def test_patch_word_es_on_phrase(client, phrase_id):
    r = client.patch(f"/api/words/{phrase_id}", json={"word_es": "romper el hielo"})
    assert r.status_code == 200
    assert r.json()["word_es"] == "romper el hielo"


def test_patch_word_es_empty_422(client, word_id):
    r = client.patch(f"/api/words/{word_id}", json={"word_es": "   "})
    assert r.status_code == 422
    assert r.json()["detail"] == "La traducción no puede estar vacía"


def test_patch_word_es_duplicate_409(client, mock_apis, word_id):
    client.post("/api/words", json={"word": "weak"})   # crea entrada con word_es = tr(weak)
    r = client.patch(f"/api/words/{word_id}", json={"word_es": "tr(weak)"})
    assert r.status_code == 409
    assert r.json()["detail"] == "Esa traducción ya existe en tu vocabulario"


def test_patch_word_es_same_entry_ok(client, word_id):
    # re-guardar la traducción propia no cuenta como duplicado
    current = next(w for w in client.get("/api/words").json() if w["id"] == word_id)
    r = client.patch(f"/api/words/{word_id}", json={"word_es": current["word_es"]})
    assert r.status_code == 200


def test_patch_unknown_id_404_wins_over_validation(client):
    r = client.patch("/api/words/no-existe", json={"word_es": "   "})
    assert r.status_code == 404


# ── quiz_enabled: checkbox de participación en el quiz ───────────────

def test_patch_quiz_enabled_bool(client, word_id):
    r = client.patch(f"/api/words/{word_id}", json={"quiz_enabled": False})
    assert r.status_code == 200
    assert r.json()["quiz_enabled"] is False
    stored = next(w for w in client.get("/api/words").json() if w["id"] == word_id)
    assert stored["quiz_enabled"] is False
    r = client.patch(f"/api/words/{word_id}", json={"quiz_enabled": True})
    assert r.json()["quiz_enabled"] is True


def test_quiz_next_excludes_disabled(client, mock_apis):
    id1 = client.post("/api/words", json={"word": "strong"}).json()["id"]
    id2 = client.post("/api/words", json={"word": "weak"}).json()["id"]
    client.patch(f"/api/words/{id1}", json={"quiz_enabled": False})
    for _ in range(10):
        q = client.get("/api/quiz/next?types=typing").json()
        assert q["word_id"] == id2


def test_quiz_next_all_disabled_404(client, mock_apis):
    wid = client.post("/api/words", json={"word": "strong"}).json()["id"]
    client.patch(f"/api/words/{wid}", json={"quiz_enabled": False})
    r = client.get("/api/quiz/next")
    assert r.status_code == 404
    assert r.json()["detail"] == "No hay palabras habilitadas para el quiz"
