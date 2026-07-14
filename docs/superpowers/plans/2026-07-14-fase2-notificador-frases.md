# Fase 2: Notificador nativo macOS + Frases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Frases multi-palabra como vocabulario + diálogo AppleScript cada N minutos que ES el quiz (responder sin navegador), con backend siempre vivo vía launchd.

**Architecture:** `add_word` bifurca por espacios (frase → solo MyMemory, sin dictionaryapi). Nuevo paquete `notifier/` con `quiz_dialog.py` (Python stdlib): funciones puras testeables (armar/parsear diálogos) + capa I/O mockeable (`api()`, `run_osascript()`) + `main()`. Dos LaunchAgents generados por `install.sh`.

**Tech Stack:** FastAPI existente · Python 3 stdlib (urllib, subprocess, pathlib) · osascript (choose from list / display dialog) · launchd LaunchAgents · pytest.

**Spec:** `docs/superpowers/specs/2026-07-14-fase2-notificador-frases-design.md` (leerlo antes de empezar).

## Global Constraints

- Detección de frase: tras `strip().lower()`, contiene espacio interno. Frase → `type: "phrase"`, solo `translate()` (MyMemory), campos ipa/pronunciation/synonym/antonym/definition/example todos `""`. Fallback `word_es or word`. El esquema de words.json NO cambia.
- Entrada máx. 80 caracteres → 400. Dedup case-insensitive existente aplica igual. El camino palabra-sola queda EXACTAMENTE como está.
- El motor de quiz (`backend/quiz.py`) NO se toca.
- `notifier/quiz_dialog.py`: SOLO stdlib. API base `http://localhost:8003`, timeout 5s. Lockfile `/tmp/elearn-quiz.lock` staleness 600s. Log `~/Library/Logs/elearn-quiz.log`. Backend caído → salir 0 silencioso. Cancelar/Saltar → NO postea respuesta.
- Diálogos: título `English Learning`. Pregunta MC → `choose from list` (botones Responder/Saltar). Typing → `display dialog` con `default answer`. Resultado → botones `{"+ Agregar", "OK"}` con `giving up after 60`. Alta → `giving up after 120`. Info → `giving up after 30`.
- Todo string interpolado en AppleScript pasa por `applescript_escape` (`\` → `\\`, `"` → `\"`).
- LaunchAgents: labels exactos `com.josemuniz.elearn-backend` (RunAtLoad+KeepAlive, corre `start.sh`) y `com.josemuniz.elearn-quiz` (StartInterval N×60). `install.sh [minutos 1-120]` default 5; `--uninstall` revierte.
- Tests: `python3 -m pytest backend/tests/ -v` desde la raíz (23 existentes + ~13 nuevos = 36).
- Commits en español, prefijos `feat:`/`test:`/`docs:`.

## File Structure

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `backend/main.py` | Modificar | Bifurcación frase en `add_word` + helper `_add_phrase` + límite 80 chars. |
| `backend/tests/test_words.py` | Crear | Tests de frases (API con externos mockeados) + elegibilidad. |
| `backend/tests/test_notifier.py` | Crear | Tests del notificador (puros + flujo con I/O mockeada). |
| `frontend/index.html` | Modificar | Placeholder y texto de ayuda mencionan frases. |
| `notifier/__init__.py` | Crear | Vacío (paquete, para importar en tests). |
| `notifier/quiz_dialog.py` | Crear | Diálogo nativo: helpers puros + I/O + main(). |
| `notifier/install.sh` | Crear | Genera plists, instala/desinstala LaunchAgents. |
| `docs/ARCHITECTURE.md`, `docs/BITACORA.md` | Modificar | Cierre (Task 5). |

---

### Task 1: Frases como vocabulario (backend + web)

**Files:**
- Modify: `backend/main.py` (función `add_word`, ~línea 172)
- Create: `backend/tests/test_words.py`
- Modify: `frontend/index.html` (2 strings del formulario)

**Interfaces:**
- Consumes: `translate(text, client)`, `fetch_dictionary(word, client)`, `datamuse_word(word, rel, client)`, `load_words()`, `save_words()` — ya en main.py. `make_word` de `backend.tests.test_quiz`.
- Produces: `POST /api/words` acepta frases (dict con `type: "phrase"`). Task 3 (notificador) usa este endpoint vía el botón "+ Agregar".

- [ ] **Step 1: Tests que fallan**

Crear `backend/tests/test_words.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/test_words.py -v`
Expected: FAIL — `test_add_phrase_skips_dictionary` recibe 404 (dictionaryapi mock no aplica al camino actual que sí lo llama... el fake devuelve dict, así que fallará el assert `type == "phrase"` con `"noun"`), `test_add_word_too_long_400` recibe 200. Los que ya pasen (duplicado, single word) está bien — el objetivo es que los de frase fallen.

- [ ] **Step 3: Implementación en main.py**

3a. En `add_word`, tras la validación de vacío, añadir el límite y la bifurcación (reemplazar el inicio de la función):

```python
@app.post("/api/words")
async def add_word(req: WordRequest):
    word = req.word.strip().lower()
    if not word:
        raise HTTPException(400, "La palabra no puede estar vacía")
    if len(word) > 80:
        raise HTTPException(400, "Máximo 80 caracteres")

    words = load_words()
    if any(w["word_en"].lower() == word for w in words):
        raise HTTPException(409, "Esa palabra ya está en tu vocabulario")

    if " " in word:
        return await _add_phrase(word, words)
```

(el resto del cuerpo actual — `async with httpx.AsyncClient() ...` — queda idéntico a continuación del `if`).

3b. Añadir el helper ANTES de `add_word`:

```python
async def _add_phrase(phrase: str, words: list) -> dict:
    """Camino frase: dictionaryapi no resuelve multi-palabra; solo se traduce."""
    async with httpx.AsyncClient() as client:
        phrase_es = await translate(phrase, client)

    data = {
        "id":           str(uuid.uuid4()),
        "created_at":   datetime.now().isoformat(),
        "word_en":      phrase,
        "word_es":      phrase_es or phrase,
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

- [ ] **Step 4: Verificar verde + suite completa**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 29 passed (23 + 6).

- [ ] **Step 5: Frontend — textos**

En `frontend/index.html`: cambiar el placeholder del input `word-input` de `"Ej: perseverance, resilient, endeavor…"` a `"Ej: perseverance, break the ice…"`, y el `<p>` de ayuda de la card "Agregar palabra" de `"Escribe en inglés y Claude generará el significado, sinónimo y frase de ejemplo."` a `"Escribe una palabra o frase en inglés; se genera traducción y, para palabras, sinónimo y ejemplo."`.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_words.py frontend/index.html
git commit -m "feat: frases multi-palabra como vocabulario (type phrase, solo traducción)"
```

---

### Task 2: Notificador — helpers puros (diálogos y parsing)

**Files:**
- Create: `notifier/__init__.py` (vacío)
- Create: `notifier/quiz_dialog.py`
- Create: `backend/tests/test_notifier.py`

**Interfaces:**
- Produces (Task 3 los orquesta): `applescript_escape(s) -> str` · `question_label(q) -> str` · `build_question_dialog(q) -> str` · `build_result_dialog(res) -> str` · `build_add_dialog() -> str` · `build_info_dialog(text) -> str` · `parse_dialog_output(raw) -> dict` con shapes `{"action": "skip"}` | `{"action": "choice", "choice": str}` | `{"action": "button", "button": str, "text": str|None}`.

- [ ] **Step 1: Tests que fallan**

Crear `backend/tests/test_notifier.py`:

```python
from notifier import quiz_dialog as nd


def test_applescript_escape():
    assert nd.applescript_escape('say "hi" \\ ok') == 'say \\"hi\\" \\\\ ok'


def test_build_question_dialog_mc():
    q = {"type": "mc_word", "direction": "en_to_es", "prompt": "strong",
         "prompt_secondary": "(strang)", "hint": "adjective",
         "options": ["fuerte", 'feliz "x"', "casa", "preciosa"]}
    s = nd.build_question_dialog(q)
    assert "choose from list" in s
    assert '"fuerte"' in s and 'feliz \\"x\\"' in s
    assert "¿Qué significa en español?" in s
    assert "(strang)" in s


def test_build_question_dialog_typing():
    q = {"type": "typing", "direction": "es_to_en",
         "prompt": "palabra", "prompt_secondary": ""}
    s = nd.build_question_dialog(q)
    assert "display dialog" in s and "default answer" in s
    assert '"Saltar", "Responder"' in s


def test_parse_choose_from_list():
    assert nd.parse_dialog_output("false") == {"action": "skip"}
    assert nd.parse_dialog_output("") == {"action": "skip"}
    assert nd.parse_dialog_output("fuerte\n") == {"action": "choice", "choice": "fuerte"}


def test_parse_display_dialog():
    r = nd.parse_dialog_output("button returned:Responder, text returned:hola, mundo")
    assert r == {"action": "button", "button": "Responder", "text": "hola, mundo"}
    assert nd.parse_dialog_output("button returned:Saltar")["action"] == "skip"
    assert nd.parse_dialog_output("button returned:Cancelar")["action"] == "skip"
    assert nd.parse_dialog_output("button returned:, gave up:true")["action"] == "skip"
    r2 = nd.parse_dialog_output("button returned:OK, gave up:false")
    assert r2 == {"action": "button", "button": "OK", "text": None}


def test_build_result_dialog():
    ok = nd.build_result_dialog({"correct": True, "correct_answer": "fuerte"})
    assert "¡Correcto!" in ok and '"+ Agregar", "OK"' in ok and "giving up after 60" in ok
    bad = nd.build_result_dialog({"correct": False, "correct_answer": "fuerte"})
    assert "Incorrecto" in bad and "fuerte" in bad
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/test_notifier.py -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'notifier'`.

- [ ] **Step 3: Implementación**

`mkdir -p notifier && touch notifier/__init__.py`. Crear `notifier/quiz_dialog.py`:

```python
"""Diálogo nativo macOS para el quiz forzado. Solo stdlib.

Helpers puros (testeables sin GUI) + capa I/O (api/run_osascript) + main().
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = "http://localhost:8003"
LOCK_FILE = Path("/tmp/elearn-quiz.lock")
LOCK_STALE_S = 600
LOG_FILE = Path.home() / "Library" / "Logs" / "elearn-quiz.log"
TITLE = "English Learning"

PROMPT_LABEL = {
    ("mc_word", "es_to_en"): "¿Cómo se dice en inglés?",
    ("mc_word", "en_to_es"): "¿Qué significa en español?",
    ("mc_phrase", "es_to_en"): "¿Cuál es la frase en inglés?",
    ("mc_phrase", "en_to_es"): "¿Qué significa esta frase?",
    ("cloze", "es_to_en"): "Completa la frase:",
    ("typing", "es_to_en"): "Escribe la traducción en inglés:",
    ("typing", "en_to_es"): "Escribe la traducción en español:",
}


# ── Helpers puros ─────────────────────────────────────────────────────

def applescript_escape(s) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def question_label(q) -> str:
    return PROMPT_LABEL.get((q["type"], q["direction"]), "Responde:")


def build_question_dialog(q) -> str:
    header = f"{question_label(q)}\n\n{q['prompt']}"
    if q.get("prompt_secondary"):
        header += f"  {q['prompt_secondary']}"
    header = applescript_escape(header)
    if q.get("options"):
        items = ", ".join(f'"{applescript_escape(o)}"' for o in q["options"])
        return (f'choose from list {{{items}}} with title "{TITLE}" '
                f'with prompt "{header}" OK button name "Responder" '
                f'cancel button name "Saltar"')
    return (f'display dialog "{header}" default answer "" '
            f'buttons {{"Saltar", "Responder"}} default button "Responder" '
            f'with title "{TITLE}"')


def build_result_dialog(res) -> str:
    if res["correct"]:
        text = f"✅ ¡Correcto!\n\n{res['correct_answer']}"
    else:
        text = f"❌ Incorrecto.\n\nEra: {res['correct_answer']}"
    return (f'display dialog "{applescript_escape(text)}" '
            f'buttons {{"+ Agregar", "OK"}} default button "OK" '
            f'with title "{TITLE}" giving up after 60')


def build_add_dialog() -> str:
    return ('display dialog "Nueva palabra o frase en inglés:" default answer "" '
            'buttons {"Cancelar", "Agregar"} default button "Agregar" '
            f'with title "{TITLE}" giving up after 120')


def build_info_dialog(text) -> str:
    return (f'display dialog "{applescript_escape(text)}" buttons {{"OK"}} '
            f'default button "OK" with title "{TITLE}" giving up after 30')


def parse_dialog_output(raw) -> dict:
    out = raw.strip()
    if not out or out == "false":
        return {"action": "skip"}
    if out.startswith("button returned:"):
        body = out[len("button returned:"):]
        gave_up = False
        if ", gave up:" in body:
            body, gave = body.rsplit(", gave up:", 1)
            gave_up = gave.strip() == "true"
        text = None
        if ", text returned:" in body:
            button, text = body.split(", text returned:", 1)
        else:
            button = body
        if gave_up or button in ("", "Saltar", "Cancelar"):
            return {"action": "skip"}
        return {"action": "button", "button": button, "text": text}
    return {"action": "choice", "choice": out}
```

- [ ] **Step 4: Verificar verde**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 35 passed (29 + 6).

- [ ] **Step 5: Commit**

```bash
git add notifier/ backend/tests/test_notifier.py
git commit -m "feat: notifier — helpers puros de diálogo AppleScript (TDD)"
```

---

### Task 3: Notificador — I/O y main()

**Files:**
- Modify: `notifier/quiz_dialog.py` (añadir al final)
- Modify: `backend/tests/test_notifier.py` (añadir al final)

**Interfaces:**
- Consumes: helpers de Task 2 · `GET /api/quiz/next` / `POST /api/quiz/answer` / `POST /api/words` (fase 1 + Task 1).
- Produces: `api(method, path, body=None) -> dict` · `run_osascript(script) -> str` · `acquire_lock() -> bool` · `log(status, detail="")` · `offer_add_word()` · `main() -> int`. Task 4 invoca el script como `/usr/bin/python3 <ABS>/notifier/quiz_dialog.py`.

- [ ] **Step 1: Tests que fallan**

Añadir a `backend/tests/test_notifier.py`:

```python
import urllib.error


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(nd, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(nd, "LOG_FILE", tmp_path / "log")
    return tmp_path


def test_main_backend_down_exits_silently(sandbox, monkeypatch):
    scripts = []
    monkeypatch.setattr(nd, "run_osascript", lambda s: scripts.append(s) or "")

    def failing_api(method, path, body=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(nd, "api", failing_api)
    assert nd.main() == 0
    assert scripts == []                    # ningún diálogo
    assert not (sandbox / "lock").exists()  # lock liberado


def test_main_lock_fresh_skips(sandbox, monkeypatch):
    (sandbox / "lock").write_text("1")
    called = []
    monkeypatch.setattr(nd, "api", lambda *a, **k: called.append(a))
    assert nd.main() == 0
    assert called == []


def test_main_full_flow_mc(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append((method, path, body))
        if path == "/api/quiz/next":
            return {"word_id": "id-1", "type": "mc_word", "direction": "en_to_es",
                    "prompt": "strong", "prompt_secondary": "", "hint": "adjective",
                    "options": ["fuerte", "feliz", "casa", "linda"]}
        return {"correct": True, "correct_answer": "fuerte", "word": {}}

    outputs = iter(["fuerte", "button returned:OK, gave up:false"])
    scripts = []

    def fake_osascript(script):
        scripts.append(script)
        return next(outputs)

    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", fake_osascript)
    assert nd.main() == 0
    assert api_calls[1] == ("POST", "/api/quiz/answer",
                            {"word_id": "id-1", "type": "mc_word",
                             "direction": "en_to_es", "answer": "fuerte"})
    assert len(scripts) == 2  # pregunta + resultado (sin "+ Agregar")


def test_main_skip_does_not_post(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append(path)
        return {"word_id": "id-1", "type": "typing", "direction": "es_to_en",
                "prompt": "palabra1", "prompt_secondary": "", "hint": "noun"}

    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", lambda s: "button returned:Saltar")
    assert nd.main() == 0
    assert api_calls == ["/api/quiz/next"]


def test_add_word_flow(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append((method, path, body))
        if path == "/api/quiz/next":
            return {"word_id": "id-1", "type": "typing", "direction": "es_to_en",
                    "prompt": "palabra1", "prompt_secondary": "", "hint": "noun"}
        if path == "/api/quiz/answer":
            return {"correct": True, "correct_answer": "word1", "word": {}}
        return {"word_en": "break the ice", "word_es": "romper el hielo"}

    outputs = iter([
        "button returned:Responder, text returned:word1",      # pregunta typing
        "button returned:+ Agregar, gave up:false",             # resultado
        "button returned:Agregar, text returned:break the ice", # alta
        "button returned:OK",                                   # confirmación
    ])
    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", lambda s: next(outputs))
    assert nd.main() == 0
    assert ("POST", "/api/words", {"word": "break the ice"}) in api_calls
```

Añadir también `import pytest` al inicio del archivo si no está.

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/test_notifier.py -v`
Expected: FAIL/ERROR — `nd.main` no existe (`AttributeError`).

- [ ] **Step 3: Implementación**

Añadir al final de `notifier/quiz_dialog.py`:

```python
# ── Capa I/O ──────────────────────────────────────────────────────────

def log(status, detail=""):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | {status} | {detail}\n")
    except OSError:
        pass


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def run_osascript(script) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=900)
    return r.stdout


def acquire_lock() -> bool:
    if LOCK_FILE.exists() and time.time() - LOCK_FILE.stat().st_mtime < LOCK_STALE_S:
        return False
    LOCK_FILE.write_text(str(int(time.time())))
    return True


# ── Orquestación ──────────────────────────────────────────────────────

def offer_add_word():
    out = parse_dialog_output(run_osascript(build_add_dialog()))
    entry = (out.get("text") or "").strip() if out["action"] == "button" else ""
    if not entry:
        return
    try:
        created = api("POST", "/api/words", {"word": entry})
        run_osascript(build_info_dialog(f"✓ {created['word_en']} → {created['word_es']}"))
        log("added", entry)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail", str(e))
        except Exception:
            detail = str(e)
        run_osascript(build_info_dialog(f"No se pudo agregar: {detail}"))
        log("add-error", detail)
    except (urllib.error.URLError, OSError) as e:
        log("add-error", str(e))


def main() -> int:
    if not acquire_lock():
        log("skip", "lock activo")
        return 0
    try:
        try:
            q = api("GET", "/api/quiz/next")
        except (urllib.error.URLError, OSError) as e:
            log("error", f"backend no disponible: {e}")
            return 0

        out = parse_dialog_output(run_osascript(build_question_dialog(q)))
        if out["action"] == "skip":
            log("skip", q["prompt"])
            return 0
        answer = out["choice"] if out["action"] == "choice" else (out.get("text") or "")
        answer = answer.strip()
        if not answer:
            log("skip", "respuesta vacía")
            return 0

        try:
            res = api("POST", "/api/quiz/answer",
                      {"word_id": q["word_id"], "type": q["type"],
                       "direction": q["direction"], "answer": answer})
        except (urllib.error.URLError, OSError) as e:
            log("error", f"answer falló: {e}")
            return 0
        log("ok" if res["correct"] else "wrong", f"{q['prompt']} -> {answer}")

        result = parse_dialog_output(run_osascript(build_result_dialog(res)))
        if result.get("button") == "+ Agregar":
            offer_add_word()
        return 0
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
```

Nota: `urllib.error.HTTPError` es subclase de `URLError` — el catch de `main()` también cubre el 404 de vocabulario vacío (ciclo silencioso, correcto).

- [ ] **Step 4: Verificar verde + suite completa**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 40 passed (35 + 5).

- [ ] **Step 5: Smoke manual sin launchd**

Con el backend corriendo (`curl -s http://localhost:8003/api/words >/dev/null && echo OK`):
Run: `python3 notifier/quiz_dialog.py &` — un diálogo nativo aparece en pantalla del usuario. NO lo respondas tú: espera 3s, verifica `pgrep -f quiz_dialog.py` (corriendo = diálogo abierto), luego limpia: `pkill -f quiz_dialog.py; pkill osascript; rm -f /tmp/elearn-quiz.lock`. Verifica que `~/Library/Logs/elearn-quiz.log` NO tiene línea de error de backend.

- [ ] **Step 6: Commit**

```bash
git add notifier/quiz_dialog.py backend/tests/test_notifier.py
git commit -m "feat: notifier — capa I/O, lockfile y main() con flujo completo (TDD)"
```

---

### Task 4: install.sh + LaunchAgents

**Files:**
- Create: `notifier/install.sh` (chmod +x)

**Interfaces:**
- Consumes: `notifier/quiz_dialog.py` (Task 3), `start.sh` (existente).
- Produces: `~/Library/LaunchAgents/com.josemuniz.elearn-backend.plist` y `com.josemuniz.elearn-quiz.plist` instalados y cargados.

- [ ] **Step 1: Crear el script**

Crear `notifier/install.sh`:

```bash
#!/bin/bash
# Instala/desinstala los LaunchAgents del quiz forzado.
# Uso: ./install.sh [minutos 1-120]   (default 5)
#      ./install.sh --uninstall
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
AGENTS_DIR="$HOME/Library/LaunchAgents"
BACKEND_PLIST="$AGENTS_DIR/com.josemuniz.elearn-backend.plist"
QUIZ_PLIST="$AGENTS_DIR/com.josemuniz.elearn-quiz.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
  launchctl unload "$QUIZ_PLIST" 2>/dev/null || true
  rm -f "$BACKEND_PLIST" "$QUIZ_PLIST"
  echo "✓ Agentes elearn desinstalados"
  exit 0
fi

MINUTES="${1:-5}"
if ! [[ "$MINUTES" =~ ^[0-9]+$ ]] || (( MINUTES < 1 || MINUTES > 120 )); then
  echo "Uso: $0 [minutos 1-120] | --uninstall" >&2
  exit 1
fi
INTERVAL=$(( MINUTES * 60 ))

mkdir -p "$AGENTS_DIR" "$HOME/Library/Logs"

cat > "$BACKEND_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.josemuniz.elearn-backend</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>$PROJECT_DIR/start.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/elearn-backend.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/elearn-backend.log</string>
</dict></plist>
EOF

cat > "$QUIZ_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.josemuniz.elearn-quiz</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>$SCRIPT_DIR/quiz_dialog.py</string>
  </array>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/elearn-quiz.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/elearn-quiz.log</string>
</dict></plist>
EOF

launchctl unload "$BACKEND_PLIST" 2>/dev/null || true
launchctl unload "$QUIZ_PLIST" 2>/dev/null || true
launchctl load "$BACKEND_PLIST"
launchctl load "$QUIZ_PLIST"

echo "✓ Backend: com.josemuniz.elearn-backend (KeepAlive, log: ~/Library/Logs/elearn-backend.log)"
echo "✓ Quiz:    com.josemuniz.elearn-quiz cada $MINUTES min (log: ~/Library/Logs/elearn-quiz.log)"
echo "  Desinstalar: $0 --uninstall"
```

Run: `chmod +x notifier/install.sh`

- [ ] **Step 2: Validar sintaxis**

Run: `bash -n notifier/install.sh && echo SYNTAX_OK`
Expected: `SYNTAX_OK`

- [ ] **Step 3: Instalar y verificar agentes**

ADVERTENCIA: esto instala agentes reales en la sesión del usuario — es el entregable pedido.
Antes: si hay un uvicorn manual corriendo en :8003, matarlo (`pkill -f 'uvicorn backend.main'`) para que launchd sea el dueño.

```bash
./notifier/install.sh 5
launchctl list | grep elearn
sleep 3 && curl -s http://localhost:8003/api/words >/dev/null && echo BACKEND_OK
```
Expected: ambos labels listados; `BACKEND_OK`.

- [ ] **Step 4: Verificar KeepAlive**

```bash
pkill -f 'uvicorn backend.main'
sleep 5
curl -s http://localhost:8003/api/words >/dev/null && echo RESURRECTED
```
Expected: `RESURRECTED` (launchd relanzó start.sh).

- [ ] **Step 5: Disparar un ciclo del quiz**

```bash
launchctl start com.josemuniz.elearn-quiz
sleep 3 && pgrep -f quiz_dialog.py && echo DIALOG_UP
```
Expected: `DIALOG_UP` (hay un diálogo en pantalla). Limpiar sin responderlo: `pkill -f quiz_dialog.py; pkill osascript; rm -f /tmp/elearn-quiz.lock`. El usuario lo probará interactivamente al final.

- [ ] **Step 6: Commit**

```bash
git add notifier/install.sh
git commit -m "feat: install.sh — LaunchAgents backend KeepAlive + quiz StartInterval"
```

---

### Task 5: Verificación E2E + docs

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `docs/BITACORA.md`

- [ ] **Step 1: Suite completa**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 40 passed.

- [ ] **Step 2: Criterios de éxito del spec §8 (los automatizables)**

1. `curl -s -X POST http://localhost:8003/api/words -H 'Content-Type: application/json' -d '{"word": "see you later"}' | python3 -m json.tool` → `type: "phrase"`, `word_es` traducida (o la frase si MyMemory limita). Luego `curl -s 'http://localhost:8003/api/quiz/next?types=mc_word' | python3 -m json.tool` varias veces hasta ver la frase como prompt u opción. Borrar la frase de prueba al final vía `DELETE /api/words/{id}` si se desea (o dejarla — es vocabulario válido; dejarla).
2. `launchctl list | grep elearn` → 2 agentes.
3. KeepAlive ya verificado en Task 4 Step 4.
4. `./notifier/install.sh --uninstall && launchctl list | grep elearn; echo "exit=$?"` → sin líneas, exit≠0 del grep. **Reinstalar de inmediato:** `./notifier/install.sh 5` (el entregable queda instalado).
5. Los criterios interactivos (responder el diálogo, "+ Agregar" desde el diálogo) quedan para el usuario — documentar en el reporte como "pendiente validación interactiva del usuario".

- [ ] **Step 3: Docs**

`docs/ARCHITECTURE.md` — añadir a la tabla de componentes:

```markdown
| Notificador nativo | Python stdlib + osascript + launchd | `notifier/quiz_dialog.py` + `notifier/install.sh` | — |
```

y tras el bloque de flujo del quiz:

```markdown
```
launchd (com.josemuniz.elearn-quiz, cada N min)
  → notifier/quiz_dialog.py → GET /api/quiz/next
  → diálogo AppleScript (choose from list / display dialog) — el quiz se responde ahí
  → POST /api/quiz/answer → resultado ✓/✗ con "+ Agregar" (POST /api/words)
launchd (com.josemuniz.elearn-backend, KeepAlive) mantiene el backend :8003 siempre vivo
```
Recomendación: con el notificador instalado, dejar el timer web desactivado (§6 del spec fase 2).
```

`docs/BITACORA.md` — añadir "## Paso 3 · Fase 2: frases + notificador nativo (2026-07-14)" siguiendo el estilo existente: Meta (1 línea), qué se construyó (frases type=phrase solo-traducción; notifier con helpers puros/I-O/main; install.sh con 2 LaunchAgents), comando de tests + output real (tail), verificación launchd real (launchctl list, KeepAlive resurrect, DIALOG_UP), archivos nuevos/modificados, próximo paso ("validación interactiva del usuario + follow-up esc() en renderWords").

- [ ] **Step 4: Commit final**

```bash
git add docs/
git commit -m "docs: bitácora paso 3 + arquitectura con notificador nativo"
```

---

## Post-plan (manual)

- Final whole-branch review + security review (workflow global) antes de merge.
- Validación interactiva del usuario: responder un diálogo real, probar "+ Agregar" con una frase.
- Follow-up pendiente de fase 1 (fuera de este plan): aplicar `esc()` en `renderWords()`.
