# Grilla + Campos Editables + Ejemplos Cortos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vista de grilla tipo planilla con edición inline por fila (pronunciación, sinónimos, antónimos, ejemplos) vía un nuevo `PATCH /api/words/{id}`, más ejemplos ≤10 palabras al generar entradas.

**Architecture:** Backend FastAPI agrega un endpoint PATCH con lista blanca Pydantic (8 campos) y un selector puro de ejemplos cortos usado por `fetch_dictionary()`. El frontend (vanilla JS, un solo `index.html`) reemplaza las tarjetas por una tabla `Inglés|Sonido|Español|Sinónimo|Antónimo|Ejemplo|acciones` con una fila en edición a la vez; las frases solo editan Sonido/IPA (restricción en UI, el endpoint es genérico).

**Tech Stack:** FastAPI + Pydantic 2.9 (usar `model_dump`), pytest + TestClient (fixtures existentes en `backend/tests/test_words.py`), vanilla JS/HTML/CSS en `frontend/index.html`.

**Spec:** `docs/superpowers/specs/2026-07-17-campos-editables-design.md`

## Global Constraints

- Trabajar en rama `feature/grilla-editable` (crear desde `main` en Task 1; no commitear directo a `main`).
- Campos editables (exactos): `pronunciation_es`, `ipa`, `synonym_en`, `synonym_es`, `antonym_en`, `antonym_es`, `example_en`, `example_es`. Ningún otro campo se modifica vía PATCH.
- Validación de ejemplos: más de **10 palabras** (contadas con `split()`) → `422` con detail exacto `"El ejemplo no puede superar 10 palabras"`.
- Mensajes de error de cara al usuario en español (consistente con el código existente).
- Frases (`type: "phrase"`): la UI no muestra ni edita sinónimo/antónimo/ejemplo; el backend NO restringe por tipo.
- `esc()` (ya existe en `frontend/index.html:774`, escapa `& < > "`) debe envolver TODO dato interpolado en el HTML de la grilla. En atributos HTML usar siempre comillas dobles (esc no escapa `'`).
- Pydantic es v2 (2.9.2): usar `model_dump(exclude_none=True)`, no `.dict()`.
- Correr pytest siempre desde la raíz del repo: `python3 -m pytest backend/tests/ -q` (suite actual: 47 passed).

---

### Task 1: Backend — `PATCH /api/words/{word_id}`

**Files:**
- Modify: `backend/main.py` (modelo junto a `WordRequest` ~línea 66; endpoint después de `delete_word` ~línea 326)
- Test (create): `backend/tests/test_edit.py`

**Interfaces:**
- Consumes: `load_words()`, `save_words()` de `backend/main.py` (existentes).
- Produces: `PATCH /api/words/{word_id}` → 200 con la entrada completa actualizada (dict del word), 404 si no existe, 422 si un ejemplo supera 10 palabras. Modelo `WordUpdateRequest` con los 8 campos opcionales. Task 3 (frontend) consume este endpoint.

- [ ] **Step 0: Crear rama**

```bash
git checkout -b feature/grilla-editable
```

- [ ] **Step 1: Write the failing tests**

Crear `backend/tests/test_edit.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backend/tests/test_edit.py -v`
Expected: FAIL — los 8 tests con `405 Method Not Allowed` (no existe PATCH aún).

- [ ] **Step 3: Write the implementation**

En `backend/main.py`, junto a los otros modelos (después de `WordRequest`, ~línea 68), agregar:

```python
class WordUpdateRequest(BaseModel):
    pronunciation_es: str | None = None
    ipa: str | None = None
    synonym_en: str | None = None
    synonym_es: str | None = None
    antonym_en: str | None = None
    antonym_es: str | None = None
    example_en: str | None = None
    example_es: str | None = None
```

Después de `delete_word` (~línea 326), agregar el endpoint:

```python
@app.patch("/api/words/{word_id}")
async def update_word(word_id: str, req: WordUpdateRequest):
    updates = {k: v.strip() for k, v in req.model_dump(exclude_none=True).items()}
    for field in ("example_en", "example_es"):
        if field in updates and len(updates[field].split()) > 10:
            raise HTTPException(422, "El ejemplo no puede superar 10 palabras")

    words = load_words()
    for w in words:
        if w["id"] == word_id:
            w.update(updates)
            save_words(words)
            return w
    raise HTTPException(404, "Palabra no encontrada")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest backend/tests/test_edit.py -v`
Expected: 10 passed (8 tests, 2 parametrizados ×2).

Run: `python3 -m pytest backend/tests/ -q`
Expected: 57 passed (47 existentes + 10 nuevos), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_edit.py
git commit -m "feat: PATCH /api/words/{id} con lista blanca de campos editables"
```

---

### Task 2: Backend — selector de ejemplos ≤10 palabras

**Files:**
- Modify: `backend/main.py` (`fetch_dictionary`, líneas 99–119; helper nuevo antes de `fetch_dictionary`)
- Test (modify): `backend/tests/test_words.py` (agregar tests al final)

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `pick_example(candidates: list[str]) -> str` — primer candidato con ≤10 palabras; si ninguno cumple, el primero recortado a 10 palabras + `"…"`; `""` si no hay candidatos. `fetch_dictionary()` la usa; su contrato externo no cambia (sigue devolviendo `example_en`).

- [ ] **Step 1: Write the failing tests**

Agregar al final de `backend/tests/test_words.py`:

```python
# ── ejemplos cortos (≤10 palabras) ───────────────────────────────────

def test_pick_example_prefers_first_short():
    from backend.main import pick_example
    assert pick_example(["Too long " * 6, "He is strong."]) == "He is strong."


def test_pick_example_keeps_order_among_short():
    from backend.main import pick_example
    assert pick_example(["First short one.", "Second short one."]) == "First short one."


def test_pick_example_truncates_when_all_long():
    from backend.main import pick_example
    long1 = "one two three four five six seven eight nine ten eleven twelve"
    out = pick_example([long1])
    assert out == "one two three four five six seven eight nine ten…"
    assert len(out.rstrip("…").split()) == 10


def test_pick_example_empty():
    from backend.main import pick_example
    assert pick_example([]) == ""
    assert pick_example(["", "   "]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest backend/tests/test_words.py -v -k pick_example`
Expected: FAIL con `ImportError: cannot import name 'pick_example'`.

- [ ] **Step 3: Write the implementation**

En `backend/main.py`, antes de `fetch_dictionary` (~línea 82), agregar:

```python
MAX_EXAMPLE_WORDS = 10

def pick_example(candidates: list[str]) -> str:
    """Primer ejemplo con ≤10 palabras; si ninguno cumple, recorta el primero."""
    candidates = [c.strip() for c in candidates if c and c.strip()]
    if not candidates:
        return ""
    for c in candidates:
        if len(c.split()) <= MAX_EXAMPLE_WORDS:
            return c
    return " ".join(candidates[0].split()[:MAX_EXAMPLE_WORDS]) + "…"
```

En `fetch_dictionary()`, reemplazar el bloque de selección de ejemplo (líneas 99–108, desde `# Find an example sentence` hasta el final del doble `for`/`break`) por:

```python
    # Find an example sentence — prefer the first one with ≤10 words
    candidates = []
    if defn.get("example"):
        candidates.append(defn["example"])
    for m in all_meanings:
        for d in m.get("definitions", []):
            if d.get("example"):
                candidates.append(d["example"])
    example_en = pick_example(candidates)
```

El bloque de fallback sintético (`if not example_en:` con los ejemplos por `partOfSpeech`, líneas 110–119) queda igual: sus ejemplos ya son cortos.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest backend/tests/ -q`
Expected: 61 passed (57 + 4 nuevos), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_words.py
git commit -m "feat: pipeline elige ejemplos de ≤10 palabras (pick_example)"
```

---

### Task 3: Frontend — grilla tipo planilla con edición inline

**Files:**
- Modify: `frontend/index.html`:
  - CSS: reemplazar regla `.words-grid` (línea 136) por estilos de tabla.
  - Contenedor: línea 222 (`<div id="words-grid" ...>`).
  - JS: reemplazar `renderWords()` completa (líneas 491–579) y agregar funciones nuevas junto a ella. `highlightWord()` (485–489) se elimina (solo la usaba `renderWords`; verificar con grep antes de borrar).

**Interfaces:**
- Consumes: `PATCH /api/words/{id}` (Task 1); existentes: `esc(s)` (línea 774), `toast(msg, type)` (línea 466), `speak(text, lang, btnId)` (línea 999), `deleteWord(id)` (línea 623), `allWords`, `const API` (línea 386).
- Produces: `renderWords()` (misma firma, ahora tabla), `renderRow(w)`, `renderEditRow(w)`, `startEdit(id)`, `cancelEdit()`, `saveEdit(id)`, `speakById(id, btnId)`, variable global `editingId`.

- [ ] **Step 1: Reemplazar CSS**

En línea 136, reemplazar:

```css
.words-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
```

por:

```css
.table-wrap { overflow-x: auto; }
.words-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.words-table th { text-align: left; padding: 8px 10px; font-size: 11px; color: var(--faint);
  text-transform: uppercase; letter-spacing: .05em; border-bottom: 1px solid var(--border); white-space: nowrap; }
.words-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
.words-table tbody tr:last-child td { border-bottom: none; }
.words-table .sub { display: block; font-size: 11px; color: var(--muted); }
.words-table input { width: 100%; min-width: 90px; box-sizing: border-box; margin-bottom: 4px;
  padding: 4px 6px; font-size: 12px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 4px; color: var(--text); }
.icon-btn { background: none; border: none; cursor: pointer; font-size: 14px; padding: 2px 4px; }
```

- [ ] **Step 2: Ajustar el contenedor**

Línea 222, reemplazar:

```html
<div id="words-grid" class="words-grid" style="display:none;"></div>
```

por:

```html
<div id="words-grid" style="display:none;"></div>
```

- [ ] **Step 3: Reemplazar `renderWords()` y agregar helpers de edición**

Verificar primero que `highlightWord` no se usa en otra parte:

Run: `grep -n "highlightWord" frontend/index.html`
Expected: solo las líneas 485 (definición) y 510 (uso dentro de renderWords).

Reemplazar el bloque completo de líneas 485–579 (desde `function highlightWord` hasta el cierre de `renderWords()` con `}).join('');` y su `}`) por:

```javascript
let editingId = null;

function speakById(id, btnId) {
  const w = allWords.find(x => x.id === id);
  if (w) speak(w.word_en, 'en-US', btnId);
}

function renderWords() {
  const grid = document.getElementById('words-grid');
  const empty = document.getElementById('empty-state');
  const badge = document.getElementById('word-count-badge');

  if (allWords.length === 0) {
    grid.style.display = 'none';
    empty.style.display = '';
    badge.style.display = 'none';
    return;
  }

  empty.style.display = 'none';
  grid.style.display = '';
  badge.style.display = '';
  badge.textContent = `${allWords.length} palabra${allWords.length !== 1 ? 's' : ''}`;

  const rows = allWords.slice().reverse()
    .map(w => (editingId === w.id ? renderEditRow(w) : renderRow(w))).join('');

  grid.innerHTML = `
    <div class="card table-wrap">
      <table class="words-table">
        <thead><tr>
          <th>Inglés</th><th>Sonido</th><th>Español</th>
          <th>Sinónimo</th><th>Antónimo</th><th>Ejemplo</th><th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

const DASH = '<span style="color:var(--faint);">—</span>';

function pairCell(en, es) {
  if (!en) return DASH;
  return `${esc(en)}${es ? `<span class="sub">${esc(es)}</span>` : ''}`;
}

function renderRow(w) {
  const wId = w.id.replace(/-/g, '');
  const isPhrase = (w.type || 'word') === 'phrase';
  return `
  <tr>
    <td style="font-weight:600; color:var(--accent);">
      ${esc(w.word_en)}
      <button class="speak-btn" id="spk-${wId}" onclick="speakById('${w.id}','spk-${wId}')" title="Escuchar">🔊</button>
    </td>
    <td>${w.pronunciation_es ? esc(w.pronunciation_es) : DASH}${w.ipa ? `<span class="sub">${esc(w.ipa)}</span>` : ''}</td>
    <td>${esc(w.word_es || '')}</td>
    ${isPhrase
      ? `<td>${DASH}</td><td>${DASH}</td><td>${DASH}</td>`
      : `<td>${pairCell(w.synonym_en, w.synonym_es)}</td>
         <td>${pairCell(w.antonym_en, w.antonym_es)}</td>
         <td>${pairCell(w.example_en, w.example_es)}</td>`}
    <td style="white-space:nowrap; text-align:right;">
      <button class="icon-btn" onclick="startEdit('${w.id}')" title="Editar">✏️</button>
      <button class="icon-btn" onclick="deleteWord('${w.id}')" title="Eliminar" style="color:var(--faint);">✕</button>
    </td>
  </tr>`;
}

function editInput(name, val, ph) {
  return `<input id="edit-${name}" value="${esc(val || '')}" placeholder="${ph}">`;
}

function renderEditRow(w) {
  const isPhrase = (w.type || 'word') === 'phrase';
  return `
  <tr style="background:var(--elevated);">
    <td style="font-weight:600; color:var(--accent);">${esc(w.word_en)}</td>
    <td>${editInput('pronunciation_es', w.pronunciation_es, 'sonido')}
        ${editInput('ipa', w.ipa, 'IPA')}</td>
    <td>${esc(w.word_es || '')}</td>
    ${isPhrase
      ? `<td colspan="3" style="color:var(--faint); font-size:12px;">— no aplica a frases —</td>`
      : `<td>${editInput('synonym_en', w.synonym_en, 'EN')}
             ${editInput('synonym_es', w.synonym_es, 'ES')}</td>
         <td>${editInput('antonym_en', w.antonym_en, 'EN')}
             ${editInput('antonym_es', w.antonym_es, 'ES')}</td>
         <td>${editInput('example_en', w.example_en, 'EN (≤10 palabras)')}
             ${editInput('example_es', w.example_es, 'ES')}</td>`}
    <td style="white-space:nowrap; text-align:right;">
      <button class="icon-btn" onclick="saveEdit('${w.id}')" title="Guardar">💾</button>
      <button class="icon-btn" onclick="cancelEdit()" title="Cancelar">✖️</button>
      <span id="edit-error" class="sub" style="color:var(--red); max-width:140px;"></span>
    </td>
  </tr>`;
}

function startEdit(id) {
  editingId = id;
  renderWords();
}

function cancelEdit() {
  editingId = null;
  renderWords();
}

const EDIT_FIELDS_WORD = ['pronunciation_es', 'ipa', 'synonym_en', 'synonym_es',
                          'antonym_en', 'antonym_es', 'example_en', 'example_es'];
const EDIT_FIELDS_PHRASE = ['pronunciation_es', 'ipa'];

async function saveEdit(id) {
  const w = allWords.find(x => x.id === id);
  if (!w) return;
  const isPhrase = (w.type || 'word') === 'phrase';
  const fields = isPhrase ? EDIT_FIELDS_PHRASE : EDIT_FIELDS_WORD;

  const body = {};
  for (const f of fields) {
    const el = document.getElementById(`edit-${f}`);
    if (el) body[f] = el.value.trim();
  }

  try {
    const res = await fetch(`${API}/api/words/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      // mostrar el error en la fila sin re-render (no perder lo tecleado)
      document.getElementById('edit-error').textContent =
        typeof err.detail === 'string' ? err.detail : 'Error al guardar';
      return;
    }
    const updated = await res.json();
    const i = allWords.findIndex(x => x.id === id);
    if (i !== -1) allWords[i] = updated;
    editingId = null;
    renderWords();
    toast('Cambios guardados', 'success');
  } catch (e) {
    document.getElementById('edit-error').textContent = 'Sin conexión con el servidor';
  }
}
```

- [ ] **Step 4: Verificación funcional en browser**

El backend corre en `http://localhost:8003` (launchd). Si no responde: `./start.sh`.

Con webapp-testing o agent-browser:

1. Abrir `http://localhost:8003` → la sección de palabras muestra la tabla con headers `Inglés | Sonido | Español | Sinónimo | Antónimo | Ejemplo`.
2. Verificar que una fila de frase muestra `—` en Sinónimo/Antónimo/Ejemplo.
3. Click ✏️ en una frase sin pronunciación → aparecen solo 2 inputs (sonido, IPA); escribir `breik de ais` en sonido → 💾 → la fila muestra `breik de ais`, toast "Cambios guardados".
4. Recargar la página → la pronunciación persiste.
5. Click ✏️ en una palabra → 8 inputs; poner en Ejemplo EN un texto de 11+ palabras → 💾 → aparece el error `El ejemplo no puede superar 10 palabras` en la fila y los inputs conservan lo tecleado.
6. Corregir a ≤10 palabras → 💾 → guarda OK.
7. Probar 🔊 en una fila (reproduce audio) y ✕ (elimina con confirmación existente).

Expected: los 7 puntos OK, sin errores en la consola del browser.

- [ ] **Step 5: Correr suite completa (regresión)**

Run: `python3 -m pytest backend/tests/ -q`
Expected: 61 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat: grilla tipo planilla con edición inline por fila (+esc en render)"
```

---

### Task 4: Cierre — reviews, bitácora y merge

**Files:**
- Modify: `docs/BITACORA.md` (agregar Paso 6 al final)

**Interfaces:**
- Consumes: rama `feature/grilla-editable` con Tasks 1–3 commiteadas.
- Produces: rama mergeada a `main` y pusheada; bitácora actualizada.

- [ ] **Step 1: Code review y security review**

Ejecutar `/code-review` (medium) sobre el diff de la rama y `/security-review` (el cambio toca API endpoints y render de datos de usuario → obligatorio). Aplicar fixes si hay hallazgos reales; re-correr `python3 -m pytest backend/tests/ -q` tras cualquier fix (Expected: 61 passed).

- [ ] **Step 2: Registrar Paso 6 en la bitácora**

Agregar al final de `docs/BITACORA.md` (ajustar números/salidas a lo realmente observado):

```markdown
---

## Paso 6 · Grilla editable + ejemplos cortos (2026-07-17)

**Meta:** Vista de grilla tipo planilla con edición inline (pronunciación, sinónimos, antónimos, ejemplos) y ejemplos ≤10 palabras al generar.

### 6.1 Qué se hizo

- `PATCH /api/words/{id}` con lista blanca de 8 campos editables; ejemplos >10 palabras → 422.
- `pick_example()`: el pipeline prefiere ejemplos de ≤10 palabras (recorta si no hay).
- Frontend: tabla `Inglés|Sonido|Español|Sinónimo|Antónimo|Ejemplo|acciones` reemplaza las tarjetas; edición inline por fila; frases solo editan sonido/IPA; `esc()` aplicado a todo el render (cierra follow-up XSS de fase 1).

### 6.2 Archivos

- **Nuevos:** `backend/tests/test_edit.py`
- **Modificados:** `backend/main.py`, `backend/tests/test_words.py`, `frontend/index.html`

### 6.3 Tests

`python3 -m pytest backend/tests/ -q` → 61 passed. Verificación en browser: edición de frase persiste tras recarga; error 422 visible en la fila.

### 6.4 Próximo paso

Validación interactiva del diálogo "+ Agregar" → Español (pendiente heredado).
```

```bash
git add docs/BITACORA.md
git commit -m "docs: bitácora paso 6 — grilla editable + ejemplos cortos"
```

- [ ] **Step 3: Merge y push**

Usar superpowers:finishing-a-development-branch. Camino esperado (convención del repo: merge a `main`):

```bash
git checkout main
git merge --no-ff feature/grilla-editable -m "Merge feature/grilla-editable: grilla editable + ejemplos cortos"
python3 -m pytest backend/tests/ -q   # Expected: 61 passed
git push origin main
git branch -d feature/grilla-editable
```

- [ ] **Step 4: Actualizar memoria**

Actualizar `MEMORY.md` del proyecto: feature completada (commit de merge), suite 61 passed, follow-up `esc()` cerrado; mover el pendiente correspondiente.
