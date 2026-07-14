# Alta bilingüe (ES/EN) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/words` acepta `lang: "en"|"es"`; la entrada en español se traduce y se enriquece con el pipeline inglés completo; toggle 🇬🇧/🇪🇸 en la web y paso de idioma en el diálogo nativo.

**Architecture:** El endpoint bifurca por `lang`. El camino ES traduce primero (ES→EN) y reusa la infraestructura existente: el pipeline inglés se extrae a un helper `_build_english_entry(word_en, words, word_es_override)` usado por ambos idiomas, y `_add_phrase` se generaliza a `(word_en, word_es, words)`. Dedup pasa a chequear `word_en` Y `word_es`.

**Tech Stack:** FastAPI + pydantic existentes · MyMemory (`translate()` ya soporta src/tgt) · vanilla JS + localStorage (`cfg` existente) · osascript.

**Spec:** `docs/superpowers/specs/2026-07-14-alta-bilingue-design.md` (leerlo antes de empezar).

## Global Constraints

- `WordRequest` gana `lang: str = "en"`; valores válidos `("en", "es")`, otro → 422 (validación explícita en el endpoint, como en quiz_next).
- Camino ES palabra: `word_en` = traducción ES→EN strip+lower; traducción vacía → 400 `"No se pudo traducir; intenta escribirla en inglés"`; pipeline inglés completo sobre la traducción; **`word_es` final = entrada original del usuario**, NO la re-traducción del pipeline.
- Regla: el camino palabra/frase lo decide **la forma del `word_en` final** (traducción multi-palabra → frase).
- Dedup: la entrada (case-insensitive) contra `word_en` Y `word_es` de todos los registros → 409; en camino ES, re-chequear la traducción contra `word_en` → 409.
- Validaciones existentes intactas: vacío 400, >80 chars 400. Esquema words.json NO cambia. Motor de quiz NO se toca.
- Web: estado en `cfg.addLang` (default `"en"`), persistido vía `saveConfig()`/restaurado en `applyConfigToUI()`. Placeholders exactos: EN `"Ej: perseverance, break the ice…"` · ES `"Ej: mariposa, romper el hielo…"`.
- Diálogo idioma: `display dialog "¿En qué idioma vas a escribir?" buttons {"Cancelar", "Español", "Inglés"} default button "Inglés" with title "English Learning" giving up after 60`. Cancelar/timeout → abortar sin POST.
- Tests: `python3 -m pytest backend/tests/ -v` — 40 existentes → 47 (5 words + 2 notifier nuevos; 1 existente actualizado).
- Commits en español, prefijos `feat:`/`test:`/`refactor:`/`docs:`.

## File Structure

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `backend/main.py` | Modificar | `lang` en modelo, `_is_duplicate`, `_add_from_spanish`, `_build_english_entry` (extracción del pipeline), `_add_phrase` generalizado. |
| `backend/tests/test_words.py` | Modificar | +5 tests ES/lang. |
| `frontend/index.html` | Modificar | Toggle EN/ES + placeholder dinámico + body con lang. |
| `notifier/quiz_dialog.py` | Modificar | `build_add_lang_dialog` + paso de idioma en `offer_add_word`. |
| `backend/tests/test_notifier.py` | Modificar | +2 tests, 1 actualizado. |
| `docs/BITACORA.md`, `docs/ARCHITECTURE.md` | Modificar | Cierre (Task 4). |

---

### Task 1: Backend — lang en/es con pipeline compartido

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_words.py`

**Interfaces:**
- Consumes: `translate(text, client, src, tgt)`, `fetch_dictionary`, `datamuse_word`, `ipa_to_spanish`, `load_words`/`save_words` — todos existentes. Fixtures `client`/`mock_apis` de test_words.py (fake_translate devuelve `f"tr({text})"` — sin espacios para entradas de una palabra, con espacios si la entrada los tiene: perfecto para probar la regla palabra/frase).
- Produces: `POST /api/words` con `{"word", "lang"}`. Helpers: `_is_duplicate(entry: str, words: list) -> bool` · `_add_from_spanish(entry_es: str, words: list) -> dict` · `_build_english_entry(word_en: str, words: list, word_es_override: str | None = None) -> dict` · `_add_phrase(word_en: str, word_es: str | None, words: list) -> dict` (None → traduce EN→ES con fallback). Tasks 2-3 consumen el endpoint.

- [ ] **Step 1: Tests que fallan**

Añadir a `backend/tests/test_words.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/test_words.py -v -k "spanish or dedup_by or lang_invalid"`
Expected: FAIL — el endpoint ignora `lang` (pydantic descarta extras): los ES devuelven el camino EN (404 del fake dictionary no, devolverá 200 con type noun y word_es="tr(...)" — asserts de word_es/word_en fallan) y el 422 devuelve 200.

- [ ] **Step 3: Implementación en main.py**

3a. Modelo:

```python
class WordRequest(BaseModel):
    word: str
    lang: str = "en"   # "en" | "es"
```

3b. Añadir helper de dedup ANTES de `_add_phrase`:

```python
def _is_duplicate(entry: str, words: list) -> bool:
    return any(entry == w["word_en"].lower()
               or entry == w.get("word_es", "").lower()
               for w in words)
```

3c. Generalizar `_add_phrase` — reemplazar COMPLETA la función por:

```python
async def _add_phrase(word_en: str, word_es, words: list) -> dict:
    """Camino frase. word_es None → traducir EN→ES con fallback a la frase."""
    if word_es is None:
        async with httpx.AsyncClient() as client:
            word_es = await translate(word_en, client)

    data = {
        "id":           str(uuid.uuid4()),
        "created_at":   datetime.now().isoformat(),
        "word_en":      word_en,
        "word_es":      word_es or word_en,
        "type":         "phrase",
        "ipa":          "",
        "pronunciation_es": "",
        "synonym_en":   "", "synonym_es": "",
        "antonym_en":   "", "antonym_es": "",
        "definition_en": "", "definition_es": "",
        "example_en":   "", "example_es": "",
        "times_practiced": 0,
        "times_correct":   0,
    }
    words.append(data)
    save_words(words)
    return data
```

3d. Extraer el pipeline inglés: crear `_build_english_entry` con TODO el cuerpo actual del camino palabra-sola de `add_word` (desde `async with httpx.AsyncClient() as client:` hasta el `return data`), parametrizado:

```python
async def _build_english_entry(word_en: str, words: list,
                               word_es_override: str | None = None) -> dict:
    """Pipeline inglés completo (dictionary + datamuse + traducciones)."""
    async with httpx.AsyncClient() as client:
        d = await fetch_dictionary(word_en, client)
        # ... (bloque actual de gathers de traducciones/datamuse, sin cambios) ...
        # ... (bloque actual de pronunciation, sin cambios) ...

    data = {
        # ... dict actual sin cambios, EXCEPTO:
        "word_es":      word_es_override or word_es or word_en,
        # ...
    }
    words.append(data)
    save_words(words)
    return data
```

(El contenido interno es el código EXISTENTE movido tal cual — solo cambian: el nombre del parámetro `word` → `word_en`, y la línea de `word_es` del dict que gana el override.)

3e. Reescribir `add_word`:

```python
@app.post("/api/words")
async def add_word(req: WordRequest):
    if req.lang not in ("en", "es"):
        raise HTTPException(422, "lang inválido (en|es)")
    word = req.word.strip().lower()
    if not word:
        raise HTTPException(400, "La palabra no puede estar vacía")
    if len(word) > 80:
        raise HTTPException(400, "Máximo 80 caracteres")

    words = load_words()
    if _is_duplicate(word, words):
        raise HTTPException(409, "Esa palabra ya está en tu vocabulario")

    if req.lang == "es":
        return await _add_from_spanish(word, words)

    if " " in word:
        return await _add_phrase(word, None, words)
    return await _build_english_entry(word, words)
```

3f. Camino español, ANTES de `add_word`:

```python
async def _add_from_spanish(entry_es: str, words: list) -> dict:
    """Entrada en español: traducir a inglés y decidir camino por la forma del word_en."""
    async with httpx.AsyncClient() as client:
        translated = await translate(entry_es, client, src="es", tgt="en")
    word_en = translated.strip().lower()
    if not word_en:
        raise HTTPException(400, "No se pudo traducir; intenta escribirla en inglés")
    if any(word_en == w["word_en"].lower() for w in words):
        raise HTTPException(409, "Esa palabra ya está en tu vocabulario")

    if " " in word_en:
        return await _add_phrase(word_en, entry_es, words)
    return await _build_english_entry(word_en, words, word_es_override=entry_es)
```

- [ ] **Step 4: Verificar verde + suite completa**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 45 passed (40 + 5).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_words.py
git commit -m "feat: alta bilingüe — lang en/es en POST /api/words con pipeline compartido"
```

---

### Task 2: Web — toggle 🇬🇧/🇪🇸

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: `cfg`/`saveConfig()`/`applyConfigToUI()` (fase 1) · `POST /api/words` con `lang` (Task 1).
- Produces: `cfg.addLang` (`"en"` default) · `setAddLang(l)`.

- [ ] **Step 1: HTML del toggle**

En la card "Agregar palabra", reemplazar la línea del input:

```html
        <input id="word-input" class="inp" type="text" placeholder="Ej: perseverance, break the ice…"
          style="flex:1;" onkeydown="if(event.key==='Enter') addWord()"/>
```

por:

```html
        <div style="display:flex; gap:6px;">
          <button class="btn-ghost" id="lang-en" onclick="setAddLang('en')" style="padding:8px 12px;">🇬🇧 EN</button>
          <button class="btn-ghost" id="lang-es" onclick="setAddLang('es')" style="padding:8px 12px;">🇪🇸 ES</button>
        </div>
        <input id="word-input" class="inp" type="text" placeholder="Ej: perseverance, break the ice…"
          style="flex:1;" onkeydown="if(event.key==='Enter') addWord()"/>
```

- [ ] **Step 2: JS**

2a. En `DEFAULT_CFG`, añadir `addLang: 'en',` (tras `perInterrupt: 1,`).

2b. Añadir junto a `setQuizMode`:

```js
const ADD_PLACEHOLDER = {
  en: 'Ej: perseverance, break the ice…',
  es: 'Ej: mariposa, romper el hielo…',
};

function setAddLang(l) {
  cfg.addLang = l;
  saveConfig();
  ['en', 'es'].forEach(m => {
    const el = document.getElementById(`lang-${m}`);
    el.style.background = m === l ? 'var(--tag-bg)' : '';
    el.style.color = m === l ? 'var(--tag-txt)' : '';
    el.style.borderColor = m === l ? 'var(--accent)' : '';
  });
  document.getElementById('word-input').placeholder = ADD_PLACEHOLDER[l];
}
```

2c. En `applyConfigToUI()`, añadir `setAddLang(cfg.addLang);`.

2d. En `addWord()`, cambiar el body del fetch a:

```js
      body: JSON.stringify({ word, lang: cfg.addLang })
```

- [ ] **Step 3: Verificar en navegador**

Backend vivo (launchd). Con agent-browser (o manual): abrir http://localhost:8003 → click 🇪🇸 → placeholder cambia a "Ej: mariposa…" → agregar "tiburón" → card muestra `shark` (o la traducción de MyMemory) con `tiburón` como español → recargar → 🇪🇸 sigue activo. Volver a 🇬🇧 y agregar una palabra en inglés → camino normal. Console limpia.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "feat: toggle EN/ES en el formulario de alta con placeholder dinámico"
```

---

### Task 3: Diálogo nativo — paso de idioma en "+ Agregar"

**Files:**
- Modify: `notifier/quiz_dialog.py`
- Modify: `backend/tests/test_notifier.py`

**Interfaces:**
- Consumes: `build_add_dialog`, `parse_dialog_output`, `run_osascript`, `api` (fase 2) · `POST /api/words` con `lang` (Task 1).
- Produces: `build_add_lang_dialog() -> str` · `offer_add_word()` con paso de idioma previo.

- [ ] **Step 1: Tests que fallan**

En `backend/tests/test_notifier.py`:

1a. Añadir:

```python
def test_build_add_lang_dialog():
    s = nd.build_add_lang_dialog()
    assert '"Cancelar", "Español", "Inglés"' in s
    assert 'default button "Inglés"' in s and "giving up after 60" in s


def test_add_word_lang_cancel_aborts(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append((method, path, body))
        if path == "/api/quiz/next":
            return {"word_id": "id-1", "type": "typing", "direction": "es_to_en",
                    "prompt": "palabra1", "prompt_secondary": "", "hint": "noun"}
        return {"correct": True, "correct_answer": "word1", "word": {}}

    outputs = iter([
        "button returned:Responder, text returned:word1",   # pregunta
        "button returned:+ Agregar, gave up:false",          # resultado
        "button returned:Cancelar",                          # idioma → cancela
    ])
    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", lambda s: next(outputs))
    assert nd.main() == 0
    assert not any(p == "/api/words" for _, p, _ in api_calls)
```

1b. ACTUALIZAR el test existente `test_add_word_flow`: en `outputs`, insertar `"button returned:Español",` entre la línea del resultado (`+ Agregar`) y la del alta (`Agregar, text returned:break the ice`), y cambiar el assert final a:

```python
    assert ("POST", "/api/words", {"word": "break the ice", "lang": "es"}) in api_calls
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/test_notifier.py -v -k "add"`
Expected: FAIL — `build_add_lang_dialog` no existe; `test_add_word_flow` falla porque el POST no lleva `lang` y la secuencia de outputs no calza.

- [ ] **Step 3: Implementación**

3a. En `notifier/quiz_dialog.py`, tras `build_add_dialog`:

```python
def build_add_lang_dialog() -> str:
    return ('display dialog "¿En qué idioma vas a escribir?" '
            'buttons {"Cancelar", "Español", "Inglés"} default button "Inglés" '
            f'with title "{TITLE}" giving up after 60')
```

3b. Reemplazar el inicio de `offer_add_word` (hasta la línea del `entry`):

```python
def offer_add_word():
    lang_out = parse_dialog_output(run_osascript(build_add_lang_dialog()))
    if lang_out["action"] != "button":
        return
    lang = "es" if lang_out["button"] == "Español" else "en"

    out = parse_dialog_output(run_osascript(build_add_dialog()))
    entry = (out.get("text") or "").strip() if out["action"] == "button" else ""
    if not entry:
        return
```

y en el POST: `api("POST", "/api/words", {"word": entry, "lang": lang})`.

- [ ] **Step 4: Verificar verde + suite completa**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 47 passed (45 + 2; `test_add_word_flow` actualizado sigue contando 1).

- [ ] **Step 5: Commit**

```bash
git add notifier/quiz_dialog.py backend/tests/test_notifier.py
git commit -m "feat: diálogo + Agregar pregunta el idioma (Español/Inglés) antes del texto"
```

---

### Task 4: E2E + docs

**Files:**
- Modify: `docs/BITACORA.md`, `docs/ARCHITECTURE.md`

- [ ] **Step 1: Suite completa**

Run: `python3 -m pytest backend/tests/ -v` → 47 passed.

- [ ] **Step 2: Criterios de éxito del spec §7 (automatizables)**

1. `curl -s -X POST http://localhost:8003/api/words -H 'Content-Type: application/json' -d '{"word": "tiburón", "lang": "es"}' | python3 -m json.tool` → `word_es: "tiburón"`, `word_en` en inglés, card rica (type/ipa/example si dictionary lo tiene). Dejar la palabra (vocabulario válido).
2. `curl -s -X POST ... -d '{"word": "tiburón", "lang": "es"}'` de nuevo → 409.
3. `curl -s -X POST ... -d '{"word": "strong", "lang": "fr"}'` → 422.
4. Criterio interactivo (diálogo con paso de idioma) → pendiente validación del usuario; documentarlo así.

- [ ] **Step 3: Docs**

`docs/ARCHITECTURE.md` — en el flujo de "Usuario escribe palabra", actualizar la primera línea a:

```markdown
Usuario escribe palabra o frase (EN o ES — selector; entrada ES se traduce primero ES→EN)
```

`docs/BITACORA.md` — añadir "## Paso 4 · Alta bilingüe ES/EN (2026-07-14)" al estilo existente: meta, qué se construyó (lang en API con pipeline compartido `_build_english_entry`, toggle web, paso de idioma en diálogo), output real de tests (47), curls del Step 2 con outputs reales, archivos, próximo paso ("validación interactiva usuario + follow-up esc() renderWords").

- [ ] **Step 4: Commit + push**

```bash
git add docs/
git commit -m "docs: bitácora paso 4 — alta bilingüe"
```

(El push a origin lo hace el controller tras el merge y las revisiones.)

---

## Post-plan (manual)

- Final whole-branch review + security review antes del merge (workflow global).
- Merge a main + `git push origin main` (ya hay remote).
- Validación interactiva del usuario: diálogo "+ Agregar" → Español → palabra nueva.
