import asyncio
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import backend.main as main
    data_file = tmp_path / "words.json"
    data_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "DATA_FILE", data_file)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    monkeypatch.setattr(main, "IMAGES_DIR", images_dir)
    return TestClient(main.app)


@pytest.fixture
def mock_apis(monkeypatch):
    import backend.main as main

    async def fake_translate(text, client, src="en", tgt="es"):
        return f"tr({text})"

    async def fake_dictionary(word, client):
        return {"word_en": word, "type": "noun", "ipa": "",
                "definition_en": "def", "example_en": f"An example with {word}.",
                "synonym_raw": "", "antonym_raw": ""}

    async def fake_datamuse(word, rel, client):
        return ""

    monkeypatch.setattr(main, "translate", fake_translate)
    monkeypatch.setattr(main, "fetch_dictionary", fake_dictionary)
    monkeypatch.setattr(main, "datamuse_word", fake_datamuse)


@pytest.fixture
def fake_gemini(monkeypatch):
    from backend import imagen
    calls = []

    async def fake_generate(word):
        calls.append(word["word_en"])
        return b"\x89PNG-fake"

    monkeypatch.setattr(imagen, "generate_scene", fake_generate)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return calls


@pytest.fixture
def word_id(client, mock_apis, monkeypatch):
    import backend.main as main
    # el alta no debe disparar generación en tests: sin keys
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    return client.post("/api/words", json={"word": "strong"}).json()["id"]


def test_generate_image_endpoint(client, word_id, fake_gemini):
    import backend.main as main
    r = client.post(f"/api/words/{word_id}/image")
    assert r.status_code == 200
    d = r.json()
    assert d["image"] == f"images/{word_id}.png"
    assert d["image_status"] == "pending"
    assert (main.IMAGES_DIR / f"{word_id}.png").read_bytes() == b"\x89PNG-fake"
    assert fake_gemini == ["strong"]


def test_generate_image_404(client, fake_gemini):
    assert client.post("/api/words/no-existe/image").status_code == 404


def test_generate_image_503_sin_key(client, word_id, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    r = client.post(f"/api/words/{word_id}/image")
    assert r.status_code == 503
    assert "GEMINI_API_KEY" in r.json()["detail"]


def test_generate_image_502_si_gemini_falla(client, word_id, monkeypatch):
    from backend import imagen

    async def boom(word):
        raise RuntimeError("cuota agotada")

    monkeypatch.setattr(imagen, "generate_scene", boom)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert client.post(f"/api/words/{word_id}/image").status_code == 502


def test_image_status_approved(client, word_id, fake_gemini):
    client.post(f"/api/words/{word_id}/image")
    r = client.put(f"/api/words/{word_id}/image/status", json={"status": "approved"})
    assert r.status_code == 200
    assert r.json()["image_status"] == "approved"


def test_image_status_none_borra_archivo(client, word_id, fake_gemini):
    import backend.main as main
    client.post(f"/api/words/{word_id}/image")
    r = client.put(f"/api/words/{word_id}/image/status", json={"status": "none"})
    assert r.status_code == 200
    assert r.json()["image"] == ""
    assert r.json()["image_status"] == "none"
    assert not (main.IMAGES_DIR / f"{word_id}.png").exists()


def test_image_status_invalido_422(client, word_id):
    r = client.put(f"/api/words/{word_id}/image/status", json={"status": "rara"})
    assert r.status_code == 422


def test_image_status_approve_sin_imagen_409(client, word_id):
    r = client.put(f"/api/words/{word_id}/image/status", json={"status": "approved"})
    assert r.status_code == 409


def test_background_task_setea_pending(client, word_id, fake_gemini):
    import backend.main as main
    asyncio.run(main._generate_image_task(word_id))
    stored = next(w for w in client.get("/api/words").json() if w["id"] == word_id)
    assert stored["image_status"] == "pending"
    assert (main.IMAGES_DIR / f"{word_id}.png").exists()


def test_add_word_sin_key_no_genera(client, mock_apis, monkeypatch, fake_gemini):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    r = client.post("/api/words", json={"word": "quiet"})
    assert r.status_code == 200
    assert fake_gemini == []          # no se llamó a Gemini


def test_build_prompt_no_pide_texto():
    from backend import imagen
    p = imagen.build_prompt({"word_en": "sneaky", "word_es": "astuto",
                             "example_en": "He was sneaky."})
    assert "sneaky" in p and "astuto" in p
    assert "no text" in p.lower()


def test_delete_word_borra_su_imagen(client, word_id, fake_gemini):
    import backend.main as main
    client.post(f"/api/words/{word_id}/image")
    assert (main.IMAGES_DIR / f"{word_id}.png").exists()
    assert client.delete(f"/api/words/{word_id}").status_code == 200
    assert not (main.IMAGES_DIR / f"{word_id}.png").exists()


# ── selección de proveedor (Qwen/DashScope prioridad, Gemini fallback) ──

def test_api_key_prioriza_dashscope(monkeypatch):
    from backend import imagen
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    assert imagen.api_key() == "qwen-key"
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    assert imagen.api_key() == "gem-key"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert imagen.api_key() == ""


def test_generate_scene_despacha_por_proveedor(monkeypatch):
    from backend import imagen

    async def fake_qwen(word):
        return b"qwen-png"

    async def fake_gemini(word):
        return b"gemini-png"

    monkeypatch.setattr(imagen, "_generate_qwen", fake_qwen)
    monkeypatch.setattr(imagen, "_generate_gemini", fake_gemini)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert asyncio.run(imagen.generate_scene({})) == b"qwen-png"
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert asyncio.run(imagen.generate_scene({})) == b"gemini-png"


def test_generate_scene_fallback_a_gemini_si_qwen_falla(monkeypatch):
    from backend import imagen

    async def qwen_roto(word):
        raise RuntimeError("Qwen HTTP 401")

    async def fake_gemini(word):
        return b"gemini-png"

    monkeypatch.setattr(imagen, "_generate_qwen", qwen_roto)
    monkeypatch.setattr(imagen, "_generate_gemini", fake_gemini)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k1")
    monkeypatch.setenv("GEMINI_API_KEY", "k2")
    assert asyncio.run(imagen.generate_scene({})) == b"gemini-png"
    # sin Gemini: el error de Qwen se propaga
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(RuntimeError, match="Qwen"):
        asyncio.run(imagen.generate_scene({}))
