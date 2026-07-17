# Imágenes/Escenas por Palabra + Quiz Visual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada palabra/frase puede tener una escena generada con Gemini, validada por el usuario (pending→approved), usada en el quiz web como tipo nuevo `mc_image` y como apoyo visual en los tipos existentes.

**Architecture:** Módulo nuevo `backend/imagen.py` aísla la llamada REST a Gemini (mockeable). `main.py` agrega storage (`data/images/` servido en `/images`), generación en background al alta, y endpoints de regeneración/estado. `quiz.py` gana el tipo `mc_image` (solo palabras con imagen aprobada) y adjunta `image_url` a todo payload con imagen aprobada. El notifier no cambia (el default de `types` en `/api/quiz/next` excluye `mc_image`). El frontend agrega columna de miniatura + lightbox de validación + render de imagen en la práctica.

**Tech Stack:** FastAPI + httpx (ya en deps), Gemini REST `gemini-3.1-flash-image-preview` (mismo modelo/endpoint que el skill banana del usuario), pytest con Gemini SIEMPRE mockeado, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-07-17-imagenes-quiz-design.md`

## Global Constraints

- Rama `feature/imagenes-quiz` (ya creada por el controller; NO commitear a `main`).
- `GEMINI_API_KEY` SIEMPRE desde `os.environ`; si falta: los endpoints de imagen responden 503 `"Generación de imágenes no configurada (GEMINI_API_KEY)"` y el alta de palabras NO falla ni genera.
- Tests NUNCA llaman a Gemini real: `backend.imagen.generate_scene` se monkeypatchea en todo test que lo alcance.
- Estados de imagen: `"none" | "pending" | "approved"`; entradas sin el campo = `"none"` (usar `.get("image_status", "none")`).
- Solo imágenes `approved` entran al quiz (elegibilidad `mc_image` y apoyo `image_url`).
- `mc_image` NO llega al diálogo nativo: el default del parámetro `types` de `GET /api/quiz/next` queda sin `mc_image` (el notifier llama sin `types`).
- Mensajes de error de cara al usuario en español.
- `esc()` envuelve todo dato interpolado en HTML nuevo; atributos con comillas dobles.
- Suite desde la raíz: `python3 -m pytest backend/tests/ -q` (actual: **70 passed**).

---

### Task 1: Backend — `imagen.py`, storage y endpoints de imagen

**Files:**
- Create: `backend/imagen.py`
- Modify: `backend/main.py` (imports, mount `/images`, task de background en `add_word`, 2 endpoints nuevos tras `update_word`)
- Test (create): `backend/tests/test_imagen.py`

**Interfaces:**
- Consumes: `load_words()`, `save_words()`, patrón de fixtures de `backend/tests/test_edit.py`.
- Produces: `imagen.api_key() -> str`, `imagen.build_prompt(word) -> str`, `async imagen.generate_scene(word) -> bytes`; `POST /api/words/{id}/image` → entrada actualizada (`image`, `image_status: "pending"`), 404/502/503; `PUT /api/words/{id}/image/status` body `{"status": "approved"|"none"}` → entrada actualizada, 404/409/422; `main.IMAGES_DIR: Path`; `async main._generate_image_task(word_id)`. Task 2 lee `image_status`; Task 3 consume los endpoints.

- [ ] **Step 1: Write the failing tests**

Crear `backend/tests/test_imagen.py`:

```python
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
    # el alta no debe disparar generación en tests: sin key
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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
    r = client.post("/api/words", json={"word": "quiet"})
    assert r.status_code == 200
    assert fake_gemini == []          # no se llamó a Gemini


def test_build_prompt_no_pide_texto():
    from backend import imagen
    p = imagen.build_prompt({"word_en": "sneaky", "word_es": "astuto",
                             "example_en": "He was sneaky."})
    assert "sneaky" in p and "astuto" in p
    assert "no text" in p.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backend/tests/test_imagen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.imagen'` (o errores 404/AttributeError equivalentes).

- [ ] **Step 3: Write `backend/imagen.py`**

```python
"""Generación de escenas con Gemini. Módulo aislado para mockearlo en tests."""
import os
import base64
import httpx

GEMINI_MODEL = "gemini-3.1-flash-image-preview"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


def api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")


def build_prompt(word: dict) -> str:
    ctx = word.get("example_en", "")
    ctx_line = f' Context: "{ctx}".' if ctx else ""
    return (
        "A simple, clean, flat illustration that clearly depicts the meaning of "
        f'the English expression "{word["word_en"]}" (Spanish: "{word.get("word_es", "")}").'
        f"{ctx_line} Friendly colors, single clear scene, easy to understand at a "
        "glance. IMPORTANT: no text, no letters, no words anywhere in the image."
    )


async def generate_scene(word: dict) -> bytes:
    """Genera la escena y devuelve los bytes PNG. Lanza RuntimeError si falla."""
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY no configurada")
    body = {
        "contents": [{"parts": [{"text": build_prompt(word)}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "4:3", "imageSize": "1K"},
        },
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(GEMINI_URL, json=body,
                              headers={"x-goog-api-key": key})
        if r.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
    candidates = data.get("candidates", [])
    if not candidates:
        reason = data.get("promptFeedback", {}).get("blockReason", "sin candidatos")
        raise RuntimeError(f"Gemini no devolvió imagen: {reason}")
    for part in candidates[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    raise RuntimeError("Respuesta de Gemini sin inlineData")
```

- [ ] **Step 4: Wire en `backend/main.py`**

Import (junto a los demás): `from backend import imagen`.

Junto a `DATA_FILE` (~línea 21):

```python
IMAGES_DIR = Path(__file__).parent.parent / "data" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
```

Localizar el mount existente del frontend (`grep -n "StaticFiles" backend/main.py`) y agregar ANTES de ese mount raíz:

```python
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
```

En `add_word`, capturar la entrada creada y agendar generación (reemplazar el bloque final de returns):

```python
    if req.lang == "es":
        created = await _add_from_spanish(word, words)
    elif " " in word:
        created = await _add_phrase(word, None, words)
    else:
        created = await _build_english_entry(word, words)
    if imagen.api_key():
        asyncio.create_task(_generate_image_task(created["id"]))
    return created
```

Helper (antes de los endpoints de imagen) y endpoints (después de `update_word`):

```python
async def _generate_image_task(word_id: str):
    """Genera la escena en background tras el alta. Best-effort: loguea y sigue."""
    words = load_words()
    target = next((w for w in words if w["id"] == word_id), None)
    if target is None:
        return
    try:
        png = await imagen.generate_scene(target)
    except Exception as e:
        print(f"[imagen] fallo generando '{target.get('word_en', '')}': {e}")
        return
    (IMAGES_DIR / f"{word_id}.png").write_bytes(png)
    words = load_words()
    for w in words:
        if w["id"] == word_id:
            w["image"] = f"images/{word_id}.png"
            w["image_status"] = "pending"
            save_words(words)
            return


@app.post("/api/words/{word_id}/image")
async def generate_word_image(word_id: str):
    if not imagen.api_key():
        raise HTTPException(503, "Generación de imágenes no configurada (GEMINI_API_KEY)")
    words = load_words()
    target = next((w for w in words if w["id"] == word_id), None)
    if target is None:
        raise HTTPException(404, "Palabra no encontrada")
    try:
        png = await imagen.generate_scene(target)
    except Exception as e:
        raise HTTPException(502, f"No se pudo generar la imagen: {e}")
    (IMAGES_DIR / f"{word_id}.png").write_bytes(png)
    target["image"] = f"images/{word_id}.png"
    target["image_status"] = "pending"
    save_words(words)
    return target


class ImageStatusRequest(BaseModel):
    status: str


@app.put("/api/words/{word_id}/image/status")
async def set_image_status(word_id: str, req: ImageStatusRequest):
    if req.status not in ("approved", "none"):
        raise HTTPException(422, "Estado inválido (approved|none)")
    words = load_words()
    target = next((w for w in words if w["id"] == word_id), None)
    if target is None:
        raise HTTPException(404, "Palabra no encontrada")
    if req.status == "none":
        (IMAGES_DIR / f"{word_id}.png").unlink(missing_ok=True)
        target["image"] = ""
        target["image_status"] = "none"
    else:
        if not target.get("image"):
            raise HTTPException(409, "La palabra no tiene imagen para aprobar")
        target["image_status"] = "approved"
    save_words(words)
    return target
```

(`ImageStatusRequest` puede vivir junto a los otros modelos si el implementador prefiere; mantener una sola definición.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest backend/tests/ -q`
Expected: **81 passed** (70 + 11 nuevos), 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/imagen.py backend/main.py backend/tests/test_imagen.py
git commit -m "feat: generación de escenas con Gemini + endpoints de imagen y validación"
```

---

### Task 2: Quiz — tipo `mc_image` y `image_url` en payloads

**Files:**
- Modify: `backend/quiz.py` (ALL_TYPES, eligible_types, build_question)
- Test (modify): `backend/tests/test_quiz.py` (agregar al final; usa el helper `make_word` existente)

**Interfaces:**
- Consumes: `image_status` de Task 1 (`.get("image_status", "none")`).
- Produces: `"mc_image"` en `ALL_TYPES`; preguntas `mc_image`: `{type: "mc_image", direction: "es_to_en", prompt: "Observa la escena", image_url: "/images/<id>.png", options: [4 word_en]}`; todo payload de palabra con imagen aprobada lleva `image_url`. El default del parámetro `types` de `/api/quiz/next` en `main.py` NO cambia (sigue sin `mc_image` → notifier excluido automáticamente). `expected_answer` no necesita cambios (`mc_image` cae en la rama `es_to_en` → `word_en`).

- [ ] **Step 1: Write the failing tests**

Agregar al final de `backend/tests/test_quiz.py`:

```python
# ── mc_image: escena → palabra ───────────────────────────────────────

def _with_image(w, status="approved"):
    w["image"] = f"images/{w['id']}.png"
    w["image_status"] = status
    return w


def test_mc_image_eligible_solo_con_imagen_aprobada():
    words = [make_word(i) for i in range(1, 6)]
    target = _with_image(words[0])
    assert "mc_image" in quiz.eligible_types(target, words, ["mc_image"])
    pending = _with_image(words[1], status="pending")
    assert "mc_image" not in quiz.eligible_types(pending, words, ["mc_image"])
    sin_imagen = words[2]
    assert "mc_image" not in quiz.eligible_types(sin_imagen, words, ["mc_image"])


def test_mc_image_no_eligible_con_pocas_palabras():
    words = [make_word(i) for i in range(1, 3)]
    target = _with_image(words[0])
    assert "mc_image" not in quiz.eligible_types(target, words, ["mc_image"])


def test_build_question_mc_image():
    words = [make_word(i) for i in range(1, 6)]
    target = _with_image(words[0])
    q = quiz.build_question(target, "mc_image", "both", words)
    assert q["type"] == "mc_image"
    assert q["direction"] == "es_to_en"
    assert q["image_url"] == f"/images/{target['id']}.png"
    assert target["word_en"] in q["options"] and len(q["options"]) == 4
    assert target["word_en"] not in q["prompt"]      # la escena no regala la respuesta


def test_image_url_de_apoyo_en_tipos_texto():
    words = [make_word(i) for i in range(1, 6)]
    target = _with_image(words[0])
    q = quiz.build_question(target, "typing", "es_to_en", words)
    assert q["image_url"] == f"/images/{target['id']}.png"


def test_sin_image_url_si_pending_o_none():
    words = [make_word(i) for i in range(1, 6)]
    pending = _with_image(words[0], status="pending")
    q = quiz.build_question(pending, "typing", "es_to_en", words)
    assert "image_url" not in q
    q2 = quiz.build_question(words[1], "mc_word", "es_to_en", words)
    assert "image_url" not in q2


def test_quiz_next_default_excluye_mc_image():
    # el notifier llama sin types: el default de main.quiz_next no debe incluirlo
    import inspect
    import backend.main as main
    default = inspect.signature(main.quiz_next).parameters["types"].default
    assert "mc_image" not in default
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backend/tests/test_quiz.py -v -k "mc_image or image_url or apoyo"`
Expected: FAIL — elegibilidad vacía y `KeyError: 'image_url'`.

- [ ] **Step 3: Implement en `backend/quiz.py`**

Línea 6:

```python
ALL_TYPES = ["mc_word", "mc_phrase", "cloze", "typing", "mc_image"]
```

En `eligible_types`, dentro del bloque `n >= 4` (después de la rama `mc_word`):

```python
        elif t == "mc_image":
            if word.get("image_status", "none") == "approved":
                out.append(t)
```

En `build_question`:
- El bloque que resuelve dirección (líneas 93–98): `mc_image` fuerza `es_to_en` igual que cloze:

```python
    if qtype in ("cloze", "mc_image"):
        resolved = "es_to_en"          # la respuesta es la palabra en inglés
    elif direction == "both":
        resolved = rng.choice(["es_to_en", "en_to_es"])
    else:
        resolved = direction
```

- Rama nueva antes de `elif qtype == "mc_phrase"`:

```python
    elif qtype == "mc_image":
        distractors = pick_distractors(word, all_words, rng)
        q["prompt"] = "Observa la escena"
        opts = [word["word_en"]] + [d["word_en"] for d in distractors]
```

(OJO: `mc_image` NO debe caer al `else: # cloze` — la cadena queda `if typing / if mc_word / elif mc_image / elif mc_phrase / else cloze`.)

- Al final, justo antes de `return q` (aplica a TODOS los tipos, incluido typing — mover el `return` temprano de typing NO: agregar el mismo bloque antes de su `return q` también, o refactorizar así):

```python
    # Apoyo visual: toda pregunta de una palabra con imagen aprobada lleva la escena
    if word.get("image_status", "none") == "approved" and word.get("image"):
        q["image_url"] = f"/{word['image']}"
```

Implementación concreta: extraer un helper y llamarlo en ambos puntos de salida:

```python
def _attach_image(q: dict, word: dict) -> dict:
    if word.get("image_status", "none") == "approved" and word.get("image"):
        q["image_url"] = f"/{word['image']}"
    return q
```

y cambiar `return q` (typing, línea 112) por `return _attach_image(q, word)` y el `return q` final por `return _attach_image(q, word)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest backend/tests/ -q`
Expected: **87 passed** (81 + 6), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add backend/quiz.py backend/tests/test_quiz.py
git commit -m "feat: tipo mc_image y apoyo visual image_url en el quiz (solo imágenes aprobadas)"
```

---

### Task 3: Frontend — miniatura, lightbox de validación y quiz visual

**Files:**
- Modify: `frontend/index.html`:
  - Grilla: header + `renderRow` + `renderEditRow` (columna 🖼 tras el checkbox → 9 columnas).
  - Funciones nuevas: `imageCell(w)`, `openImageModal(id)`, `closeImageModal()`, `generateImage(id)`, `setImageStatus(id, status)`, `generateMissing()`.
  - Práctica: `renderQuestion` (bloque de imagen), `PROMPT_LABEL` (+`mc_image`), `DEFAULT_CFG.types` y checkbox de tipo.
  - Botón "🎨 Generar faltantes" junto al badge de conteo de palabras.

**Interfaces:**
- Consumes: `POST /api/words/{id}/image`, `PUT /api/words/{id}/image/status` (Task 1); payloads con `image_url` y tipo `mc_image` (Task 2); helpers existentes `esc/toast/loadWords/allWords/API/isQuizEnabled`.
- Produces: UI completa; sin API nueva.

- [ ] **Step 1: Grilla — columna 🖼**

Header (en `renderWords`, tras el `<th>` del checkbox ✓):

```html
<th title="Escena">🖼</th>
```

Función nueva junto a `quizCheckCell`:

```javascript
function imageCell(w) {
  const status = w.image_status || 'none';
  if (status === 'none') {
    return `<td><button class="icon-btn" onclick="generateImage('${w.id}')" title="Generar escena">🎨</button></td>`;
  }
  const badge = status === 'pending'
    ? `<span class="sub" style="color:var(--accent);">pendiente</span>` : '';
  return `<td style="text-align:center;">
    <img src="${API}/${esc(w.image)}?v=${Date.now()}" alt="escena" loading="lazy"
      onclick="openImageModal('${w.id}')"
      style="width:40px; height:30px; object-fit:cover; border-radius:4px; cursor:zoom-in;">
    ${badge}</td>`;
}
```

En `renderRow` y `renderEditRow`: insertar `${imageCell(w)}` inmediatamente después de `${quizCheckCell(w)}` / `${quizCheckCell(w, true)}`. (La fila de edición de frases usa `colspan="3"`; el resto de celdas no cambia — verificar que ambas filas queden con 9 `<td>` equivalentes.)

- [ ] **Step 2: Lightbox de validación**

HTML: junto al modal existente (buscar `grep -n "max-width:540px" frontend/index.html`), agregar como hermano:

```html
<!-- Lightbox de imagen -->
<div id="image-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:60; align-items:center; justify-content:center;" onclick="if(event.target===this) closeImageModal()">
  <div class="card" style="max-width:560px; width:92%; padding:20px; text-align:center;">
    <p id="image-modal-word" style="font-size:18px; font-weight:700; color:var(--accent); margin-bottom:10px;"></p>
    <img id="image-modal-img" src="" alt="escena" style="max-width:100%; max-height:60vh; border-radius:8px; margin-bottom:14px;">
    <p id="image-modal-hint" style="font-size:12px; color:var(--muted); margin-bottom:12px;"></p>
    <div id="image-modal-actions" style="display:flex; gap:10px; justify-content:center; flex-wrap:wrap;"></div>
  </div>
</div>
```

JS (junto a `imageCell`):

```javascript
function openImageModal(id) {
  const w = allWords.find(x => x.id === id);
  if (!w || !w.image) return;
  const m = document.getElementById('image-modal');
  document.getElementById('image-modal-word').textContent = `${w.word_en} · ${w.word_es}`;
  document.getElementById('image-modal-img').src = `${API}/${w.image}?v=${Date.now()}`;
  document.getElementById('image-modal-hint').textContent =
    w.image_status === 'pending'
      ? '¿Entiendes la escena? Apruébala para que el quiz la use.'
      : 'Escena aprobada — el quiz la está usando.';
  const btn = (label, fn) =>
    `<button class="btn-ghost" style="padding:8px 14px;" onclick="${fn}">${label}</button>`;
  document.getElementById('image-modal-actions').innerHTML =
    (w.image_status === 'pending' ? btn('✓ La entiendo (aprobar)', `setImageStatus('${w.id}','approved')`) : '') +
    btn('🎨 Regenerar', `generateImage('${w.id}')`) +
    btn('✕ Descartar', `setImageStatus('${w.id}','none')`);
  m.style.display = 'flex';
}

function closeImageModal() {
  document.getElementById('image-modal').style.display = 'none';
}

async function generateImage(id) {
  toast('Generando escena…', 'info');
  try {
    const res = await fetch(`${API}/api/words/${id}/image`, { method: 'POST' });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Error al generar');
    const updated = await res.json();
    const i = allWords.findIndex(x => x.id === id);
    if (i !== -1) allWords[i] = updated;
    closeImageModal();
    renderWords();
    toast('Escena lista — revísala y apruébala', 'success');
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function setImageStatus(id, status) {
  try {
    const res = await fetch(`${API}/api/words/${id}/image/status`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Error');
    const updated = await res.json();
    const i = allWords.findIndex(x => x.id === id);
    if (i !== -1) allWords[i] = updated;
    closeImageModal();
    renderWords();
    toast(status === 'approved' ? 'Escena aprobada ✓' : 'Escena descartada', 'success');
  } catch (e) {
    toast(e.message, 'error');
  }
}
```

- [ ] **Step 3: "Generar faltantes"**

Junto al badge `word-count-badge` (buscar `grep -n "word-count-badge" frontend/index.html`, agregar botón hermano en el HTML de esa sección):

```html
<button class="btn-ghost" id="gen-missing-btn" onclick="generateMissing()" style="padding:6px 12px; font-size:12px;">🎨 Generar faltantes</button>
```

```javascript
let genMissingStop = false;

async function generateMissing() {
  const btn = document.getElementById('gen-missing-btn');
  if (btn.dataset.running === '1') { genMissingStop = true; return; }
  const missing = allWords.filter(w => !(w.image_status && w.image_status !== 'none'));
  if (missing.length === 0) { toast('Todas las palabras tienen escena', 'info'); return; }
  btn.dataset.running = '1';
  genMissingStop = false;
  for (let i = 0; i < missing.length; i++) {
    if (genMissingStop) break;
    btn.textContent = `⏸ ${i + 1}/${missing.length} (click para parar)`;
    try {
      const res = await fetch(`${API}/api/words/${missing[i].id}/image`, { method: 'POST' });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))).detail || 'error';
        toast(`${missing[i].word_en}: ${err}`, 'error');
        if (res.status === 503) break;       // sin key: no insistir
      }
    } catch { toast('Sin conexión', 'error'); break; }
  }
  btn.dataset.running = '';
  btn.textContent = '🎨 Generar faltantes';
  await loadWords();
  toast('Generación terminada — revisa y aprueba las escenas', 'success');
}
```

- [ ] **Step 4: Práctica — render de imagen y tipo nuevo**

`PROMPT_LABEL`: agregar la entrada:

```javascript
  mc_image: { es_to_en: '¿Qué palabra o frase representa esta escena?' },
```

`renderQuestion`: después de la línea del label (`<p ...>${label}...</p>`), insertar:

```javascript
  const imgBlock = q.image_url
    ? `<img src="${API}${esc(q.image_url)}" alt="escena"
        style="max-width:100%; max-height:${q.type === 'mc_image' ? '260' : '120'}px;
        border-radius:8px; margin-bottom:10px; display:block;">`
    : '';
```

y concatenar `${imgBlock}` en el template justo tras el `</p>` del label. Para `mc_image` el prompt "Observa la escena" se muestra igual que cualquier prompt (sin cambios extra).

`DEFAULT_CFG.types` (línea ~406): agregar `'mc_image'` a la lista. Checkbox en la sección de tipos (tras la línea de `mc_phrase`, ~263):

```html
<label><input type="checkbox" id="type-mc_image" checked onchange="toggleType('mc_image')"/> Escena (imagen)</label>
```

Verificar con `grep -n "type-\${t}\|updateTypesUI\|TYPES_UI" frontend/index.html` qué lista recorre la UI de checkboxes y agregar `mc_image` ahí también si es una lista literal. Nota conocida: usuarios con config guardada en localStorage no tendrán `mc_image` activo hasta marcarlo — aceptable.

- [ ] **Step 5: Verificación funcional en browser (Gemini mockeado NO aplica aquí — usar backend real SIN key para la parte de errores, y con key para el flujo completo)**

Con webapp-testing/Playwright contra `http://localhost:8003`:

1. La grilla muestra la columna 🖼 (9 columnas) con 🎨 en palabras sin imagen.
2. Click 🎨 en una palabra → (con `GEMINI_API_KEY` en el entorno del server) aparece miniatura con badge "pendiente". Si el server no tiene key (launchd), verificar el 503 con toast claro y ejecutarse el resto con imágenes generadas vía curl con key local si es posible — documentar cuál de los dos caminos se dio.
3. Click miniatura → lightbox con "✓ La entiendo (aprobar)" → aprobar → badge desaparece.
4. Práctica: con la palabra aprobada, tras varias preguntas aparece la escena como apoyo; forzar `mc_image` (cfg solo con ese tipo) → imagen 260px + 4 opciones; responder correcto.
5. Descartar desde lightbox → vuelve el botón 🎨 y el archivo se borra (`ls data/images/`).
6. Consola del browser sin errores.

- [ ] **Step 6: Suite + commit**

Run: `python3 -m pytest backend/tests/ -q` → Expected: **87 passed**.

```bash
git add frontend/index.html
git commit -m "feat: miniatura + lightbox de validación de escenas y quiz visual en la web"
```

---

### Task 4: Cierre — env launchd, reviews, bitácora y merge

**Files:**
- Modify: `notifier/install.sh` (inyectar `GEMINI_API_KEY` al plist del backend)
- Modify: `docs/BITACORA.md` (Paso 7)
- Modify: `.gitignore` — verificar que `data/images/` SÍ se versiona (no ignorar; las imágenes son datos del usuario)

**Interfaces:**
- Consumes: rama con Tasks 1–3.
- Produces: rama mergeada a `main` y pusheada; launchd con la key.

- [ ] **Step 1: `install.sh` — EnvironmentVariables**

En el heredoc del plist del backend (`BACKEND_PLIST`), dentro del `<dict>` principal, agregar (solo si `GEMINI_API_KEY` está presente en el entorno del instalador; si no, `echo` de aviso y continuar):

```bash
GEMINI_KEY_XML=""
if [ -n "${GEMINI_API_KEY:-}" ]; then
  GEMINI_KEY_XML="<key>EnvironmentVariables</key><dict><key>GEMINI_API_KEY</key><string>${GEMINI_API_KEY}</string></dict>"
else
  echo "AVISO: GEMINI_API_KEY no está en el entorno; la generación de imágenes quedará deshabilitada en el backend de launchd." >&2
fi
```

e interpolar `${GEMINI_KEY_XML}` dentro del `<dict>` del plist del backend. (El plist vive en `~/Library/LaunchAgents`, fuera del repo público — la key NO toca git.)

- [ ] **Step 2: Reviews**

`/code-review` (medium) del diff de la rama + `/security-review` (obligatorio: endpoints nuevos, subprocesos no — pero sí llamada externa con API key y archivos escritos desde red). Atención especial: la key nunca logueada ni committeada; `word_id` viene de path param y se usa en nombre de archivo — verificar que no hay path traversal (los ids son UUIDs generados por el server, y `IMAGES_DIR / f"{word_id}.png"` con un id arbitrario tipo `../x` sería un riesgo → el 404 por lookup en words.json lo bloquea antes; el reviewer debe confirmarlo). Aplicar fixes y re-correr suite.

- [ ] **Step 3: Bitácora Paso 7 + memoria**

Registrar en `docs/BITACORA.md` (formato de pasos anteriores, con números reales observados: tests, archivos, verificación browser). Actualizar `MEMORY.md` (feature completada, follow-ups).

```bash
git add docs/BITACORA.md notifier/install.sh
git commit -m "docs: bitácora paso 7 — imágenes/escenas con validación; install.sh inyecta GEMINI_API_KEY"
```

- [ ] **Step 4: Merge y push**

```bash
git checkout main
git merge --no-ff feature/imagenes-quiz -m "Merge feature/imagenes-quiz: escenas por palabra con validación + quiz visual"
python3 -m pytest backend/tests/ -q   # Expected: 87 passed
git push origin main
git branch -d feature/imagenes-quiz
```

Redeploy launchd para que el backend reciba la key: `bash notifier/install.sh` (con la key en el entorno) — validar que el backend de launchd responde y que `POST /api/words/{id}/image` ya no da 503.
