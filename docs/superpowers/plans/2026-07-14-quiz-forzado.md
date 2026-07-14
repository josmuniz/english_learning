# Quiz Forzado Configurable — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interrumpir al usuario cada N minutos (configurable, mín 1) con un modal de quiz de 4 tipos de pregunta, con selección de palabras ponderada por fallos y match tolerante.

**Architecture:** Motor de quiz stateless en el backend (`backend/quiz.py` puro + 2 endpoints en `backend/main.py`); el frontend (single-file `frontend/index.html`) solo pinta: config persistente en localStorage, timer que sobrevive recargas, y un renderer de preguntas compartido entre el modal y la sesión de práctica.

**Tech Stack:** FastAPI + pydantic (ya instalados) · pytest + fastapi TestClient (nuevo, dev-only) · Vanilla JS + localStorage.

**Spec:** `docs/superpowers/specs/2026-07-14-quiz-forzado-design.md` (leerlo antes de empezar).

## Global Constraints

- Tipos de pregunta exactos: `mc_word`, `mc_phrase`, `cloze`, `typing`. Direcciones: `es_to_en`, `en_to_es`, `both`.
- `cloze` ignora `direction` (siempre inglés; emite `direction: "es_to_en"` porque la respuesta es EN).
- Ponderación: peso 3.0 si `times_practiced == 0`; si no, `1 + 4*(1 - times_correct/times_practiced)`.
- Match tolerante: strip + lowercase + sin acentos (NFD) + sin artículo inicial (`el|la|los|las|un|una|unos|unas|the|a|an`) + espacios colapsados; acepta sinónimo en `mc_word`/`typing`.
- Con `< 4` palabras en vocabulario, los tipos de opción múltiple degradan a `typing`.
- La respuesta correcta NUNCA viaja en el payload de `GET /api/quiz/next`.
- `/api/quiz/check` se ELIMINA (el frontend migra a `/api/quiz/answer`).
- El esquema de `data/words.json` NO cambia.
- localStorage key: `elearn_config`.
- Correr tests: `python3 -m pytest backend/tests/ -v` desde la raíz del proyecto.
- El servidor corre con `./start.sh` (uvicorn :8003, `--reload`).
- Commits en español, prefijos `feat:`/`test:`/`refactor:`/`docs:`.

## File Structure

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `backend/quiz.py` | Crear | Motor puro: normalización, match, pesos, selección, elegibilidad, armado de preguntas. Sin I/O ni FastAPI. |
| `backend/main.py` | Modificar | 2 endpoints nuevos (`/api/quiz/next`, `/api/quiz/answer`), eliminar `/api/quiz/check`, mover `import asyncio` al top. |
| `backend/tests/__init__.py` | Crear | Vacío (paquete). |
| `backend/tests/test_quiz.py` | Crear | Unit tests del motor + tests de API con TestClient. |
| `requirements-dev.txt` | Crear | `pytest>=8.0.0` |
| `frontend/index.html` | Modificar | Config card nueva, timer persistente, modal de quiz, sesión migrada al motor. |
| `docs/BITACORA.md` | Modificar | Paso 2 al cierre. |

---

### Task 1: Motor — normalización y match tolerante

**Files:**
- Create: `backend/quiz.py`
- Create: `backend/tests/__init__.py` (vacío)
- Create: `backend/tests/test_quiz.py`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces: `quiz.normalize(text: str) -> str` · `quiz.is_match(answer: str, expected: str, synonym: str = "") -> bool` · `quiz.ALL_TYPES = ["mc_word", "mc_phrase", "cloze", "typing"]` · helper de tests `make_word(i, **over) -> dict` (usado por TODOS los tests posteriores).

- [ ] **Step 1: Instalar pytest**

```bash
printf 'pytest>=8.0.0\n' > requirements-dev.txt
python3 -m pip install -r requirements-dev.txt
mkdir -p backend/tests && touch backend/tests/__init__.py
```

- [ ] **Step 2: Escribir los tests que fallan**

Crear `backend/tests/test_quiz.py`:

```python
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
```

- [ ] **Step 3: Verificar que fallan**

Run: `python3 -m pytest backend/tests/ -v`
Expected: FAIL / ERROR con `ModuleNotFoundError: No module named 'backend.quiz'` (o `AttributeError`).

- [ ] **Step 4: Implementación mínima**

Crear `backend/quiz.py`:

```python
"""Motor de quiz: puro, sin I/O. Consumido por main.py y por los tests."""
import random
import re
import unicodedata

ALL_TYPES = ["mc_word", "mc_phrase", "cloze", "typing"]

_ARTICLES = re.compile(r"^(el|la|los|las|un|una|unos|unas|the|a|an)\s+", re.IGNORECASE)


def normalize(text: str) -> str:
    s = text.strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _ARTICLES.sub("", s)
    s = re.sub(r"\s+", " ", s)
    return s


def is_match(answer: str, expected: str, synonym: str = "") -> bool:
    a = normalize(answer)
    if not a:
        return False
    if a == normalize(expected):
        return True
    return bool(synonym.strip()) and a == normalize(synonym)
```

- [ ] **Step 5: Verificar que pasan**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/quiz.py backend/tests/ requirements-dev.txt
git commit -m "feat: motor de quiz — normalización y match tolerante (TDD)"
```

---

### Task 2: Motor — ponderación por fallos y selección

**Files:**
- Modify: `backend/quiz.py`
- Modify: `backend/tests/test_quiz.py`

**Interfaces:**
- Consumes: `make_word` (Task 1).
- Produces: `quiz.word_weight(w: dict) -> float` · `quiz.pick_word(words: list[dict], rng=random) -> dict`.

- [ ] **Step 1: Tests que fallan**

Añadir a `backend/tests/test_quiz.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/ -v -k weight or pick`
Expected: FAIL con `AttributeError: module 'backend.quiz' has no attribute 'word_weight'`.

- [ ] **Step 3: Implementación**

Añadir a `backend/quiz.py`:

```python
def word_weight(w: dict) -> float:
    tp = w.get("times_practiced", 0)
    if tp == 0:
        return 3.0
    return 1.0 + 4.0 * (1 - w.get("times_correct", 0) / tp)


def pick_word(words: list, rng=random) -> dict:
    weights = [word_weight(w) for w in words]
    return rng.choices(words, weights=weights, k=1)[0]
```

- [ ] **Step 4: Verificar que pasan**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/quiz.py backend/tests/test_quiz.py
git commit -m "feat: selección de palabras ponderada por fallos"
```

---

### Task 3: Motor — respuesta esperada y elegibilidad de tipos

**Files:**
- Modify: `backend/quiz.py`
- Modify: `backend/tests/test_quiz.py`

**Interfaces:**
- Consumes: `make_word`, `quiz.ALL_TYPES`.
- Produces: `quiz.expected_answer(word: dict, qtype: str, direction: str) -> tuple[str, str]` (retorna `(esperada, sinonimo)`) · `quiz.eligible_types(word: dict, all_words: list, requested: list[str]) -> list[str]` · `quiz.choose_type(word: dict, all_words: list, requested: list[str], rng=random) -> str`.

- [ ] **Step 1: Tests que fallan**

Añadir a `backend/tests/test_quiz.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/ -v`
Expected: FAIL con `AttributeError` (expected_answer / eligible_types no existen).

- [ ] **Step 3: Implementación**

Añadir a `backend/quiz.py`:

```python
def expected_answer(word: dict, qtype: str, direction: str) -> tuple:
    if qtype == "cloze":
        return word["word_en"], ""
    if qtype == "mc_phrase":
        if direction == "en_to_es":
            return word["example_es"], ""
        return word["example_en"], ""
    if direction == "es_to_en":
        return word["word_en"], word.get("synonym_en", "")
    return word["word_es"], word.get("synonym_es", "")


def _has_examples(w: dict) -> bool:
    return bool(w.get("example_en")) and bool(w.get("example_es"))


def eligible_types(word: dict, all_words: list, requested: list) -> list:
    n = len(all_words)
    out = []
    for t in requested:
        if t == "typing":
            out.append(t)
        elif n < 4:
            continue
        elif t == "mc_word":
            out.append(t)
        elif t == "cloze":
            if word.get("example_en") and word["word_en"].lower() in word["example_en"].lower():
                out.append(t)
        elif t == "mc_phrase":
            if _has_examples(word):
                donors = [w for w in all_words if w["id"] != word["id"] and _has_examples(w)]
                if len(donors) >= 3:
                    out.append(t)
    return out


def choose_type(word: dict, all_words: list, requested: list, rng=random) -> str:
    elig = eligible_types(word, all_words, requested)
    if elig:
        return rng.choice(elig)
    return "mc_word" if len(all_words) >= 4 else "typing"
```

- [ ] **Step 4: Verificar que pasan**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/quiz.py backend/tests/test_quiz.py
git commit -m "feat: respuesta esperada y elegibilidad de tipos de pregunta"
```

---

### Task 4: Motor — armado de preguntas con distractores

**Files:**
- Modify: `backend/quiz.py`
- Modify: `backend/tests/test_quiz.py`

**Interfaces:**
- Consumes: `expected_answer`, `_has_examples` (Task 3), `make_word`.
- Produces: `quiz.pick_distractors(word, all_words, rng=random, need_example=False) -> list[dict]` · `quiz.build_question(word: dict, qtype: str, direction: str, all_words: list, rng=random) -> dict` con claves `word_id, type, direction, prompt, prompt_secondary, hint` y `options` (solo tipos MC).

- [ ] **Step 1: Tests que fallan**

Añadir a `backend/tests/test_quiz.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/ -v -k build or typing or both or cloze or phrase`
Expected: FAIL con `AttributeError: ... no attribute 'build_question'`.

- [ ] **Step 3: Implementación**

Añadir a `backend/quiz.py`:

```python
def pick_distractors(word: dict, all_words: list, rng=random, need_example: bool = False) -> list:
    pool = [w for w in all_words if w["id"] != word["id"]]
    if need_example:
        pool = [w for w in pool if _has_examples(w)]
    return rng.sample(pool, 3)


def build_question(word: dict, qtype: str, direction: str, all_words: list, rng=random) -> dict:
    if qtype == "cloze":
        resolved = "es_to_en"          # la respuesta es la palabra en inglés
    elif direction == "both":
        resolved = rng.choice(["es_to_en", "en_to_es"])
    else:
        resolved = direction

    q = {
        "word_id": word["id"],
        "type": qtype,
        "direction": resolved,
        "hint": word.get("type", "word"),
        "prompt_secondary": "",
    }

    if qtype == "typing":
        q["prompt"] = word["word_es"] if resolved == "es_to_en" else word["word_en"]
        if resolved == "en_to_es" and word.get("pronunciation_es"):
            q["prompt_secondary"] = f'({word["pronunciation_es"]})'
        return q

    if qtype == "mc_word":
        distractors = pick_distractors(word, all_words, rng)
        if resolved == "en_to_es":
            q["prompt"] = word["word_en"]
            if word.get("pronunciation_es"):
                q["prompt_secondary"] = f'({word["pronunciation_es"]})'
            opts = [word["word_es"]] + [d["word_es"] for d in distractors]
        else:
            q["prompt"] = word["word_es"]
            opts = [word["word_en"]] + [d["word_en"] for d in distractors]
    elif qtype == "mc_phrase":
        distractors = pick_distractors(word, all_words, rng, need_example=True)
        if resolved == "en_to_es":
            q["prompt"] = word["example_en"]
            opts = [word["example_es"]] + [d["example_es"] for d in distractors]
        else:
            q["prompt"] = word["example_es"]
            opts = [word["example_en"]] + [d["example_en"] for d in distractors]
    else:  # cloze
        distractors = pick_distractors(word, all_words, rng)
        pattern = re.compile(re.escape(word["word_en"]), re.IGNORECASE)
        q["prompt"] = pattern.sub("____", word["example_en"], count=1)
        opts = [word["word_en"]] + [d["word_en"] for d in distractors]

    rng.shuffle(opts)
    q["options"] = opts
    return q
```

- [ ] **Step 4: Verificar que pasan**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/quiz.py backend/tests/test_quiz.py
git commit -m "feat: armado de preguntas mc_word/mc_phrase/cloze/typing con distractores"
```

---

### Task 5: API — GET /api/quiz/next y POST /api/quiz/answer

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_quiz.py`

**Interfaces:**
- Consumes: todo `backend/quiz.py` (Tasks 1-4) · `load_words()`/`save_words()` existentes en main.py.
- Produces: `GET /api/quiz/next?types=&direction=` → JSON de `build_question` · `POST /api/quiz/answer` body `{word_id, type, direction, answer}` → `{correct, correct_answer, word}`. **Elimina** `POST /api/quiz/check` y `QuizCheckRequest`.

- [ ] **Step 1: Tests de API que fallan**

Añadir a `backend/tests/test_quiz.py`:

```python
# ── API ──────────────────────────────────────────────────────────────

from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import backend.main as main
    data_file = tmp_path / "words.json"
    data_file.write_text(
        json.dumps([make_word(i) for i in range(1, 6)]), encoding="utf-8")
    monkeypatch.setattr(main, "DATA_FILE", data_file)
    return TestClient(main.app)


def test_quiz_next_returns_question(client):
    r = client.get("/api/quiz/next?types=mc_word&direction=en_to_es")
    assert r.status_code == 200
    q = r.json()
    assert q["type"] == "mc_word"
    assert len(q["options"]) == 4
    assert "correct_answer" not in q


def test_quiz_next_empty_vocab_404(tmp_path, monkeypatch):
    import backend.main as main
    data_file = tmp_path / "words.json"
    data_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(main, "DATA_FILE", data_file)
    r = TestClient(main.app).get("/api/quiz/next")
    assert r.status_code == 404


def test_quiz_next_invalid_types_422(client):
    assert client.get("/api/quiz/next?types=foo,bar").status_code == 422


def test_quiz_answer_updates_stats(client, tmp_path):
    body = {"word_id": "id-1", "type": "mc_word",
            "direction": "en_to_es", "answer": "palabra1"}
    r = client.post("/api/quiz/answer", json=body)
    assert r.status_code == 200
    assert r.json()["correct"] is True
    saved = json.loads((tmp_path / "words.json").read_text(encoding="utf-8"))
    w1 = next(w for w in saved if w["id"] == "id-1")
    assert w1["times_practiced"] == 1 and w1["times_correct"] == 1


def test_quiz_answer_tolerant_and_wrong(client):
    ok = client.post("/api/quiz/answer", json={
        "word_id": "id-1", "type": "typing",
        "direction": "en_to_es", "answer": "  La PALABRA1 "})
    assert ok.json()["correct"] is True
    bad = client.post("/api/quiz/answer", json={
        "word_id": "id-1", "type": "typing",
        "direction": "en_to_es", "answer": "otra cosa"})
    assert bad.json()["correct"] is False
    assert bad.json()["correct_answer"] == "palabra1"


def test_quiz_answer_unknown_word_404(client):
    r = client.post("/api/quiz/answer", json={
        "word_id": "nope", "type": "typing",
        "direction": "en_to_es", "answer": "x"})
    assert r.status_code == 404
```

- [ ] **Step 2: Verificar que fallan**

Run: `python3 -m pytest backend/tests/ -v -k quiz_next or quiz_answer`
Expected: FAIL con 404 (ruta no existe) en los de `quiz_next` / `quiz_answer`.

- [ ] **Step 3: Implementación en main.py**

En `backend/main.py`:

3a. Arriba, junto a los otros imports (y BORRAR la línea `import asyncio` que está al final del archivo, sección "Missing import"):

```python
import asyncio

from backend import quiz as quiz_engine
```

3b. Reemplazar COMPLETO el modelo `QuizCheckRequest` (líneas ~71-74) por:

```python
class QuizAnswerRequest(BaseModel):
    word_id: str
    type: str        # mc_word | mc_phrase | cloze | typing
    direction: str   # es_to_en | en_to_es
    answer: str
```

3c. Reemplazar COMPLETO el endpoint `@app.post("/api/quiz/check")` (función `check_quiz`) por:

```python
@app.get("/api/quiz/next")
async def quiz_next(types: str = "mc_word,mc_phrase,cloze,typing",
                    direction: str = "both"):
    requested = [t.strip() for t in types.split(",")
                 if t.strip() in quiz_engine.ALL_TYPES]
    if not requested:
        raise HTTPException(422, "types no contiene ningún tipo válido")
    if direction not in ("es_to_en", "en_to_es", "both"):
        raise HTTPException(422, "direction inválida")
    words = load_words()
    if not words:
        raise HTTPException(404, "El vocabulario está vacío")
    word = quiz_engine.pick_word(words)
    qtype = quiz_engine.choose_type(word, words, requested)
    return quiz_engine.build_question(word, qtype, direction, words)


@app.post("/api/quiz/answer")
async def quiz_answer(req: QuizAnswerRequest):
    words = load_words()
    word = next((w for w in words if w["id"] == req.word_id), None)
    if not word:
        raise HTTPException(404, "Palabra no encontrada")

    expected, synonym = quiz_engine.expected_answer(word, req.type, req.direction)
    is_correct = quiz_engine.is_match(req.answer, expected, synonym)

    for w in words:
        if w["id"] == req.word_id:
            w["times_practiced"] = w.get("times_practiced", 0) + 1
            if is_correct:
                w["times_correct"] = w.get("times_correct", 0) + 1
    save_words(words)

    return {"correct": is_correct, "correct_answer": expected, "word": word}
```

- [ ] **Step 4: Verificar que pasan todos**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 21 passed.

- [ ] **Step 5: Smoke test manual del endpoint**

```bash
./start.sh &   # o verificar que ya corre
sleep 2
curl -s 'http://localhost:8003/api/quiz/next?types=mc_word' | python3 -m json.tool
```
Expected: JSON con `word_id`, `type: "mc_word"`, `options` de 4, sin `correct_answer`.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_quiz.py
git commit -m "feat: endpoints /api/quiz/next y /api/quiz/answer; elimina /api/quiz/check"
```

---

### Task 6: Frontend — config card con presets, tipos y persistencia

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: nada del backend (solo localStorage).
- Produces: objeto global `cfg` `{intervalMin, direction, types[], perInterrupt, timerActive, timerEndsAt}` + `saveConfig()` + `loadConfig()`. Los globals viejos `intervalMinutes` y `quizMode` DESAPARECEN (todo lee de `cfg`). Task 7 y 8 dependen de `cfg` y `saveConfig()`.

- [ ] **Step 1: Reemplazar el HTML del selector de intervalo**

En la card "⏱ Recordatorio automático", reemplazar el bloque:

```html
          <div style="display:flex; gap:8px;">
            <button class="btn-ghost" id="int-15" onclick="setInterval_(15)" style="flex:1;">15 min</button>
            <button class="btn-ghost" id="int-20" onclick="setInterval_(20)" style="flex:1;">20 min</button>
          </div>
```

por:

```html
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn-ghost" id="int-5"  onclick="setIntervalMin(5)"  style="flex:1;">5 min</button>
            <button class="btn-ghost" id="int-10" onclick="setIntervalMin(10)" style="flex:1;">10 min</button>
            <button class="btn-ghost" id="int-15" onclick="setIntervalMin(15)" style="flex:1;">15 min</button>
            <button class="btn-ghost" id="int-30" onclick="setIntervalMin(30)" style="flex:1;">30 min</button>
            <input id="int-custom" class="inp" type="number" min="1" max="120" placeholder="otro"
              style="flex:1; min-width:70px; padding:8px 10px;"
              onchange="setIntervalMin(parseInt(this.value)||15)"/>
          </div>
          <div style="margin-top:12px;">
            <p style="font-size:12px; color:var(--muted); margin-bottom:8px; text-transform:uppercase; letter-spacing:.05em;">Tipos de pregunta</p>
            <div style="display:flex; gap:12px; flex-wrap:wrap; font-size:13px;">
              <label><input type="checkbox" id="type-mc_word" checked onchange="toggleType('mc_word')"/> Palabra (opciones)</label>
              <label><input type="checkbox" id="type-mc_phrase" checked onchange="toggleType('mc_phrase')"/> Frase (opciones)</label>
              <label><input type="checkbox" id="type-cloze" checked onchange="toggleType('cloze')"/> Completar hueco</label>
              <label><input type="checkbox" id="type-typing" checked onchange="toggleType('typing')"/> Escribir</label>
            </div>
          </div>
          <div style="margin-top:12px;">
            <p style="font-size:12px; color:var(--muted); margin-bottom:8px; text-transform:uppercase; letter-spacing:.05em;">Preguntas por interrupción</p>
            <select id="per-interrupt" class="inp" style="width:auto; padding:6px 10px;" onchange="cfg.perInterrupt=parseInt(this.value); saveConfig();">
              <option value="1">1</option><option value="3">3</option><option value="5">5</option>
            </select>
          </div>
```

- [ ] **Step 2: Reemplazar el estado global y agregar persistencia**

En el `<script>`, reemplazar el bloque de estado:

```js
let allWords = [];
let timerActive = false;
let intervalMinutes = 15;
let timerSeconds = 0;
let timerTotal = 0;
let timerTick = null;
let quizMode = 'both';
```

por:

```js
let allWords = [];
let timerTick = null;
let timerSeconds = 0;   // transitorio: Task 7 los elimina al reescribir el timer
let timerTotal = 0;

const CONFIG_KEY = 'elearn_config';
const DEFAULT_CFG = {
  intervalMin: 15, direction: 'both',
  types: ['mc_word', 'mc_phrase', 'cloze', 'typing'],
  perInterrupt: 1, timerActive: false, timerEndsAt: null,
};
let cfg = loadConfig();

function loadConfig() {
  try { return { ...DEFAULT_CFG, ...JSON.parse(localStorage.getItem(CONFIG_KEY) || '{}') }; }
  catch { return { ...DEFAULT_CFG }; }
}
function saveConfig() { localStorage.setItem(CONFIG_KEY, JSON.stringify(cfg)); }

function setIntervalMin(min) {
  cfg.intervalMin = Math.max(1, Math.min(120, min));
  saveConfig();
  ['5','10','15','30'].forEach(m => {
    const el = document.getElementById(`int-${m}`);
    const active = cfg.intervalMin === parseInt(m);
    el.style.background = active ? 'var(--tag-bg)' : '';
    el.style.color = active ? 'var(--tag-txt)' : '';
    el.style.borderColor = active ? 'var(--accent)' : '';
  });
  const custom = document.getElementById('int-custom');
  if (!['5','10','15','30'].includes(String(cfg.intervalMin))) custom.value = cfg.intervalMin;
}

function toggleType(t) {
  const idx = cfg.types.indexOf(t);
  if (idx >= 0) cfg.types.splice(idx, 1); else cfg.types.push(t);
  if (cfg.types.length === 0) {          // nunca dejar 0 tipos
    cfg.types.push(t);
    document.getElementById(`type-${t}`).checked = true;
    toast('Debe haber al menos un tipo activo', 'error');
  }
  saveConfig();
}

function applyConfigToUI() {
  setIntervalMin(cfg.intervalMin);
  setQuizMode(cfg.direction);
  ['mc_word','mc_phrase','cloze','typing'].forEach(t => {
    document.getElementById(`type-${t}`).checked = cfg.types.includes(t);
  });
  document.getElementById('per-interrupt').value = String(cfg.perInterrupt);
}
```

- [ ] **Step 3: Migrar `setQuizMode` y `setInterval_` a cfg**

Reemplazar las funciones `setQuizMode(mode)` y `setInterval_(min)` existentes por (nota: `setInterval_` se ELIMINA, ya reemplazada por `setIntervalMin` arriba):

```js
function setQuizMode(mode) {
  cfg.direction = mode;
  saveConfig();
  ['both', 'es_to_en', 'en_to_es'].forEach(m => {
    const el = document.getElementById(`mode-${m}`);
    el.style.background = m === mode ? 'var(--tag-bg)' : '';
    el.style.color = m === mode ? 'var(--tag-txt)' : '';
    el.style.borderColor = m === mode ? 'var(--accent)' : '';
  });
}
```

Y reemplazar el bloque `// ── Init ──` final:

```js
setInterval_(15);
setQuizMode('both');
loadWords();
```

por:

```js
applyConfigToUI();
loadWords();
```

- [ ] **Step 4: Buscar referencias rotas**

Run: `grep -n 'intervalMinutes\|quizMode\|setInterval_' frontend/index.html`
Sustituir TODAS las ocurrencias restantes para que la app siga funcionando en este commit (Task 7 reescribe el timer, pero este task debe dejar todo verde):
- `intervalMinutes` → `cfg.intervalMin` (en `startTimer`, `showSummary`)
- `timerActive` → `cfg.timerActive` (en `toggleTimer`, `startTimer`, `stopTimer`, `showSummary`; donde se asigna, añadir `saveConfig();` en la línea siguiente)
- `quizMode` → `cfg.direction` (en `loadQuestion`, 2 ocurrencias)

Re-run del grep: sin resultados.

- [ ] **Step 4b: Aviso de vocabulario chico (spec §5.3)**

En `updatePracticeSection()`, reemplazar la asignación de `hint.textContent` por:

```js
  hint.textContent = !has
    ? 'Necesitas al menos 1 palabra en tu vocabulario para practicar.'
    : allWords.length < 4
      ? `Tienes ${allWords.length} palabra(s). Agrega al menos 4 para activar la opción múltiple (por ahora todo será de escribir).`
      : `Tienes ${allWords.length} palabras listas para practicar.`;
```

- [ ] **Step 5: Verificar en el navegador**

```bash
open http://localhost:8003
```
En la tab Práctica: elegir 10 min, desmarcar "Escribir", elegir 3 preguntas → recargar la página → la selección persiste (10 min activo, checkbox apagado, select en 3).

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat: config card con presets 5/10/15/30 + campo libre + tipos + persistencia localStorage"
```

---

### Task 7: Frontend — timer persistente + modal de quiz

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: `cfg`, `saveConfig()` (Task 6) · `GET /api/quiz/next` y `POST /api/quiz/answer` (Task 5).
- Produces: `openQuizModal(n)` · `fetchNextQuestion() -> Promise<q>` · `renderQuestion(q, container, onDone)` — reutilizados por Task 8. `fireTimerAlert()` ahora abre el modal (ya no llama `startPractice()`).

- [ ] **Step 1: Agregar el HTML del modal**

Antes de `<div id="toast"></div>`, insertar:

```html
<!-- Quiz modal (interrupción) -->
<div id="quiz-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,.65); z-index:100; align-items:center; justify-content:center;">
  <div class="card" style="max-width:540px; width:92%; padding:24px;">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px;">
      <span style="font-size:13px; font-weight:700;">🎯 ¡Hora de practicar!</span>
      <span style="font-size:12px; color:var(--muted);" id="qm-progress"></span>
    </div>
    <div id="qm-body"></div>
    <div id="qm-actions" style="margin-top:16px; text-align:right;"></div>
  </div>
</div>
```

- [ ] **Step 2: Reescribir el timer para que persista**

Eliminar `let timerSeconds = 0;` y `let timerTotal = 0;` del estado (transitorios de Task 6). Reemplazar COMPLETAS las funciones `toggleTimer`, `startTimer`, `stopTimer`, `tickTimer`, `fireTimerAlert` por:

```js
function toggleTimer() { cfg.timerActive ? stopTimer() : startTimer(); }

function startTimer() {
  if (allWords.length === 0) { toast('Agrega palabras primero', 'error'); return; }
  requestNotifPermission();
  cfg.timerActive = true;
  cfg.timerEndsAt = Date.now() + cfg.intervalMin * 60 * 1000;
  saveConfig();
  armTimerUI();
  toast(`⏱ Timer activado: cada ${cfg.intervalMin} minutos`, 'success');
}

function armTimerUI() {
  document.getElementById('timer-toggle-btn').textContent = 'Desactivar';
  document.getElementById('timer-toggle-btn').style.background = 'var(--red)';
  document.getElementById('timer-status-text').innerHTML =
    '<span style="display:flex;align-items:center;gap:6px;"><span class="pulse-dot"></span> Activo</span>';
  document.getElementById('ring-subtitle').textContent = 'Próxima práctica en…';
  clearInterval(timerTick);
  timerTick = setInterval(tickTimer, 1000);
  tickTimer();
}

function stopTimer() {
  cfg.timerActive = false;
  cfg.timerEndsAt = null;
  saveConfig();
  clearInterval(timerTick);
  document.getElementById('timer-toggle-btn').textContent = 'Activar';
  document.getElementById('timer-toggle-btn').style.background = '';
  document.getElementById('timer-status-text').textContent = 'Desactivado';
  document.getElementById('timer-next-text').textContent = '';
  document.getElementById('timer-label').textContent = '--:--';
  document.getElementById('ring-fill').style.strokeDashoffset = '276.46';
  document.getElementById('ring-subtitle').textContent = 'Activa el timer para comenzar';
}

function tickTimer() {
  const remaining = Math.max(0, Math.round((cfg.timerEndsAt - Date.now()) / 1000));
  const total = cfg.intervalMin * 60;
  const m = Math.floor(remaining / 60).toString().padStart(2, '0');
  const s = (remaining % 60).toString().padStart(2, '0');
  document.getElementById('timer-label').textContent = `${m}:${s}`;
  document.getElementById('ring-fill').style.strokeDashoffset =
    276.46 * (1 - remaining / total);
  document.getElementById('timer-next-text').textContent =
    `A las ${new Date(cfg.timerEndsAt).toLocaleTimeString('es-CL', {hour:'2-digit',minute:'2-digit'})}`;
  if (remaining <= 0) { clearInterval(timerTick); fireTimerAlert(); }
}

function fireTimerAlert() {
  toast('🎯 ¡Es hora de practicar!', 'success');
  if (Notification.permission === 'granted' && document.hidden) {
    const n = new Notification('English Learning', {
      body: '¡Es hora de practicar! Click para responder.',
    });
    n.onclick = () => { window.focus(); n.close(); };
  }
  openQuizModal(cfg.perInterrupt);
}

function rearmTimer() {
  if (!cfg.timerActive) return;
  cfg.timerEndsAt = Date.now() + cfg.intervalMin * 60 * 1000;
  saveConfig();
  armTimerUI();
}
```

- [ ] **Step 3: Agregar el motor de UI del quiz (compartido modal/sesión)**

Agregar después de las funciones del timer:

```js
// ── Quiz UI compartida ─────────────────────────────────────────────
async function fetchNextQuestion() {
  const params = new URLSearchParams({ types: cfg.types.join(','), direction: cfg.direction });
  const res = await fetch(`${API}/api/quiz/next?${params}`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Error al obtener pregunta');
  return res.json();
}

async function sendAnswer(q, answer) {
  const res = await fetch(`${API}/api/quiz/answer`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ word_id: q.word_id, type: q.type, direction: q.direction, answer }),
  });
  return res.json();
}

const PROMPT_LABEL = {
  mc_word:  { es_to_en: '¿Cómo se dice en inglés?', en_to_es: '¿Qué significa en español?' },
  mc_phrase:{ es_to_en: '¿Cuál es la frase en inglés?', en_to_es: '¿Qué significa esta frase?' },
  cloze:    { es_to_en: 'Completa la frase:' },
  typing:   { es_to_en: 'Escribe la traducción en inglés:', en_to_es: 'Escribe la traducción en español:' },
};

function renderQuestion(q, container, onDone) {
  const label = (PROMPT_LABEL[q.type] || {})[q.direction] || 'Responde:';
  const speakLang = (q.direction === 'en_to_es' || q.type === 'cloze') ? 'en-US' : 'es-ES';
  const promptSize = q.type.startsWith('mc_') || q.type === 'cloze' ? 18 : 30;
  let html = `
    <p style="font-size:12px; color:var(--muted); margin-bottom:8px;">${label}
      <span class="badge badge-green" style="margin-left:6px;">${q.direction === 'es_to_en' ? '🇪🇸 → 🇬🇧' : '🇬🇧 → 🇪🇸'}</span></p>
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">
      <p style="font-size:${promptSize}px; font-weight:700; color:var(--accent); margin:0;">${q.prompt}</p>
      <button class="speak-btn" onclick="speak(${JSON.stringify(q.prompt)}, '${speakLang}', null)" title="Escuchar">🔊</button>
    </div>
    ${q.prompt_secondary ? `<p class="pronunciation">${q.prompt_secondary}</p>` : ''}
    <p style="font-size:12px; color:var(--faint); font-style:italic; margin-bottom:14px;">Tipo: ${q.hint}</p>`;

  if (q.options) {
    html += `<div style="display:grid; gap:8px;">` + q.options.map(o =>
      `<button class="btn-ghost qopt" style="text-align:left;" onclick="answerFromUI(this, ${JSON.stringify(o).replace(/"/g,'&quot;')})">${o}</button>`
    ).join('') + `</div>`;
  } else {
    html += `
      <div style="display:flex; gap:10px;">
        <input id="q-typing-input" class="inp" type="text" placeholder="Tu respuesta…"
          onkeydown="if(event.key==='Enter') answerFromUI(null, this.value)"/>
        <button class="btn-primary" onclick="answerFromUI(null, document.getElementById('q-typing-input').value)">Verificar</button>
      </div>`;
  }
  html += `<div id="q-feedback" style="margin-top:14px;"></div>`;
  container.innerHTML = html;

  // closure para que los onclick lleguen a esta pregunta
  window.answerFromUI = async (btnEl, answer) => {
    if (!answer || !answer.trim()) return;
    container.querySelectorAll('button.qopt, .btn-primary, #q-typing-input').forEach(el => el.disabled = true);
    const data = await sendAnswer(q, answer.trim());
    const fb = container.querySelector('#q-feedback');
    fb.innerHTML = data.correct
      ? `<div style="background:color-mix(in srgb,var(--green) 10%,transparent);border:1px solid color-mix(in srgb,var(--green) 30%,transparent);border-radius:8px;padding:10px 14px;">✅ <strong style="color:var(--green);">¡Correcto!</strong> <span style="font-size:12px;color:var(--muted);">${data.correct_answer}</span></div>`
      : `<div style="background:color-mix(in srgb,var(--red) 10%,transparent);border:1px solid color-mix(in srgb,var(--red) 30%,transparent);border-radius:8px;padding:10px 14px;">❌ <strong style="color:var(--red);">Incorrecto.</strong> <span style="font-size:12px;color:var(--muted);">Era: <strong style="color:var(--text);">${data.correct_answer}</strong></span></div>`;
    if (btnEl) btnEl.style.borderColor = data.correct ? 'var(--green)' : 'var(--red)';
    onDone(data);
  };
  const inp = container.querySelector('#q-typing-input');
  if (inp) setTimeout(() => inp.focus(), 100);
}

// ── Modal ──────────────────────────────────────────────────────────
let modalTotal = 0, modalDone = 0, modalCorrect = 0;

async function openQuizModal(n) {
  modalTotal = n; modalDone = 0; modalCorrect = 0;
  document.getElementById('quiz-modal').style.display = 'flex';
  await modalNextQuestion();
}

async function modalNextQuestion() {
  document.getElementById('qm-progress').textContent = `Pregunta ${modalDone + 1} de ${modalTotal}`;
  document.getElementById('qm-actions').innerHTML = '';
  try {
    const q = await fetchNextQuestion();
    renderQuestion(q, document.getElementById('qm-body'), (data) => {
      modalDone++;
      if (data.correct) modalCorrect++;
      const last = modalDone >= modalTotal;
      document.getElementById('qm-actions').innerHTML = last
        ? `<button class="btn-primary" onclick="closeQuizModal()">Cerrar (${modalCorrect}/${modalTotal})</button>`
        : `<button class="btn-primary" onclick="modalNextQuestion()">Siguiente →</button>`;
    });
  } catch (e) {
    document.getElementById('qm-body').innerHTML =
      `<p style="color:var(--red); font-size:13px;">${e.message}</p>`;
    document.getElementById('qm-actions').innerHTML =
      `<button class="btn-ghost" onclick="closeQuizModal()">Cerrar</button>`;
  }
}

function closeQuizModal() {
  document.getElementById('quiz-modal').style.display = 'none';
  rearmTimer();
  loadWords();   // refresca stats en las cards
}
```

- [ ] **Step 4: Rearmar timer al cargar + gancho ?quiz=1**

Reemplazar el bloque `// ── Init ──` (dejado por Task 6) por:

```js
applyConfigToUI();
loadWords().then(() => {
  if (new URLSearchParams(location.search).get('quiz') === '1') {
    openQuizModal(cfg.perInterrupt);
  } else if (cfg.timerActive && cfg.timerEndsAt) {
    if (cfg.timerEndsAt <= Date.now()) fireTimerAlert();
    else armTimerUI();
  } else if (cfg.timerActive) {
    stopTimer();
  }
});
```

(`loadWords` ya es `async`, retorna Promise.)

- [ ] **Step 5: Verificar referencias viejas eliminadas**

Run: `grep -n 'timerSeconds\|timerTotal\|intervalMinutes\|timerActive' frontend/index.html | grep -v 'cfg\.'`
Expected: sin resultados (todo migrado a `cfg.*`). `showSummary` ya usa `cfg.timerActive`/`cfg.intervalMin` (Task 6 Step 4).

- [ ] **Step 6: Verificar en el navegador**

1. `open 'http://localhost:8003/?quiz=1'` → el modal aparece de inmediato con una pregunta; responder muestra feedback y "Cerrar".
2. Poner intervalo custom en 1 min, activar timer, esperar 60s → modal aparece solo; al cerrar, el ring reinicia.
3. Con timer activo, recargar la página → el countdown continúa donde iba (no desde cero).

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html
git commit -m "feat: timer persistente + modal de quiz con 4 tipos y gancho ?quiz=1"
```

---

### Task 8: Frontend — migrar sesión de práctica al motor

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: `fetchNextQuestion()`, `renderQuestion()` (Task 7) · `cfg` (Task 6).
- Produces: sesión de práctica sin lógica propia de armado/validación. Se ELIMINAN: `submitQuizAnswer`, `speakFlashcard`, y el HTML interno del flashcard (input `quiz-input`, botón `quiz-submit-btn`).

- [ ] **Step 1: Simplificar el HTML del paso flashcard**

Reemplazar TODO el contenido interno de `<div id="step-flashcard" class="card" …>` (el header "Flashcard", el `<div class="flashcard">` completo y el footer con `quiz-input`/`quiz-submit-btn`) por:

```html
      <div id="step-flashcard" class="card" style="padding:0; overflow:hidden;">
        <div style="padding:12px 20px; border-bottom:1px solid var(--border);">
          <span style="font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em;">Pregunta</span>
        </div>
        <div id="session-question" style="padding:24px;"></div>
      </div>
```

- [ ] **Step 2: Reescribir loadQuestion y eliminar lógica duplicada**

Reemplazar COMPLETAS las funciones `loadQuestion()` y `submitQuizAnswer()` (eliminar también `speakFlashcard()` y las variables `currentWord`/`currentQuizType` del estado de sesión — dejar solo `let currentAnswerWord = null;`) por:

```js
async function loadQuestion() {
  const total = sessionWords;   // ahora es un número (ver startPractice)
  document.getElementById('session-progress-text').textContent = `Pregunta ${sessionIdx + 1} de ${total}`;
  document.getElementById('session-score-text').textContent = `✓ ${sessionCorrect} · ✗ ${sessionWrong}`;
  document.getElementById('session-progress-bar').style.width = `${(sessionIdx / total) * 100}%`;

  document.getElementById('step-sentence').style.display = 'none';
  document.getElementById('step-next').style.display = 'none';
  document.getElementById('step-flashcard').style.display = '';

  const q = await fetchNextQuestion();
  renderQuestion(q, document.getElementById('session-question'), (data) => {
    currentAnswerWord = data.word;
    if (data.correct) { sessionCorrect++; showSentenceStep(); }
    else { sessionWrong++; document.getElementById('step-next').style.display = ''; }
    document.getElementById('session-score-text').textContent = `✓ ${sessionCorrect} · ✗ ${sessionWrong}`;
  });
}
```

- [ ] **Step 3: Ajustar startPractice y showSentenceStep**

Reemplazar `startPractice()` por (sessionWords pasa de array a número de preguntas — el servidor elige cada palabra):

```js
function startPractice() {
  if (allWords.length === 0) return;
  sessionWords = Math.min(5, Math.max(1, allWords.length));
  sessionIdx = 0; sessionCorrect = 0; sessionWrong = 0;
  document.getElementById('practice-start-section').style.display = 'none';
  document.getElementById('practice-session').style.display = '';
  document.getElementById('session-summary').style.display = 'none';
  loadQuestion();
}
```

En `showSentenceStep()` y `submitSentence()`, reemplazar `currentWord.word_en` por `currentAnswerWord.word_en` y `currentWord.example_en` por `currentAnswerWord.example_en` (3 ocurrencias en total). En `nextQuestion()` y `showSummary()`, reemplazar `sessionWords.length` por `sessionWords` (3 ocurrencias). Eliminar la función `shuffle()` (ya sin uso).

- [ ] **Step 4: Verificar que no quedan referencias rotas**

Run: `grep -n 'currentWord\|currentQuizType\|quizMode\|sessionWords\.length\|shuffle(' frontend/index.html`
Expected: sin resultados.

- [ ] **Step 5: Verificar en el navegador**

`open http://localhost:8003` → tab Práctica → "Iniciar sesión de práctica": 5 preguntas de tipos variados; responder correcto muestra el paso de frase; el resumen final muestra el score; las cards de Vocabulario reflejan los contadores al volver.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "refactor: sesión de práctica consume el motor /api/quiz/next (elimina lógica duplicada)"
```

---

### Task 9: Verificación end-to-end + cierre

**Files:**
- Modify: `docs/BITACORA.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Suite completa**

Run: `python3 -m pytest backend/tests/ -v`
Expected: 21 passed.

- [ ] **Step 2: Flujo real (criterio de éxito del spec §10)**

Con `./start.sh` corriendo:
1. `curl -s 'http://localhost:8003/api/quiz/next' | python3 -m json.tool` → pregunta válida.
2. En el navegador: intervalo 1 min (campo custom) + timer activo → esperar el modal → responder → verificar en la card de la palabra que `Practicado 1×` aparece.
3. Recargar con el timer corriendo → countdown continúa.
4. `http://localhost:8003/?quiz=1` → modal inmediato.
5. Fallar una palabra 3 veces seguidas (modal o sesión) y verificar que reaparece pronto (peso 5×).

- [ ] **Step 3: Actualizar docs**

En `docs/ARCHITECTURE.md`, añadir a la tabla de componentes la fila:

```markdown
| Motor de quiz | Python puro (sin I/O) | `backend/quiz.py` | — |
```

y bajo "Flujo de datos" el bloque:

```markdown
Timer (frontend, persistente en localStorage)
  → GET /api/quiz/next (ponderado por fallos, 4 tipos, distractores del propio vocabulario)
  → modal responde → POST /api/quiz/answer (match tolerante) → stats en words.json
```

En `docs/BITACORA.md`, agregar "Paso 2 · Quiz forzado implementado" con: meta, comandos de test con su output real, archivos nuevos/modificados y próximo paso (fase 2 notificador macOS).

- [ ] **Step 4: Commit final**

```bash
git add docs/
git commit -m "docs: bitácora paso 2 + arquitectura con motor de quiz"
```

---

## Post-plan (manual, fuera de los tasks)

- `/verify` sobre el flujo (skill del workflow global) · `/code-review` del diff · `/security-review` del branch — obligatorios por CLAUDE.md antes de dar por cerrado.
- Fase 2 (notificador macOS con launchd + osascript) queda para otra sesión; el gancho `?quiz=1` ya está listo.
