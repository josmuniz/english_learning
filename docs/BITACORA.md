# English Learning App — Bitacora de Desarrollo

**Repositorio:** local (sin remote propio)
**Stack:** FastAPI + Uvicorn (backend) · HTML/JS single-file (frontend) · JSON file storage
**Fecha inicio:** 2026-05-13 (bitacora inicializada retroactivamente el 2026-07-14)

---

## Paso 0 · Estado inicial del proyecto (retro-documentado 2026-07-14)

**Meta:** App personal para aprender vocabulario en inglés: guardar palabras con definición, traducción al español y pronunciación aproximada en fonética española.

### 0.1 Arquitectura

```
frontend/index.html (921 líneas, single-file UI)
        │  fetch
        ▼
backend/main.py (342 líneas, FastAPI :8003)
        │
        ├── api.dictionaryapi.dev   → definiciones + IPA
        ├── api.mymemory.translated → traducción EN→ES
        ├── api.datamuse.com        → palabras relacionadas
        ▼
data/words.json (persistencia, 96 líneas actuales)
```

### 0.2 Características clave

- Conversor IPA → fonética española legible (`ipa_to_spanish`, mapa de dígrafos con orden significativo)
- Sin base de datos: `words.json` leído/escrito completo por request
- CORS abierto (`allow_origins=["*"]`) — app local
- Arranque: `./start.sh` → `uvicorn backend.main:app --port 8003 --reload`
- Config en `.env` (cargado por start.sh)

### 0.3 Estado

- Sin tests
- Sin docs previas (esta bitácora es la primera)
- Sin sección en MEMORY.md global
- Directorio `.superpowers/brainstorm/` presente pero con contenido vacío

### 0.4 Próximo paso

Definir objetivo de la sesión 2026-07-14.

---

## Paso 1 · Sesión 2026-07-14 (en curso)

**Meta:** Diseñar "quiz forzado" — preguntas aleatorias configurables cada N minutos con opción múltiple, para forzar aprendizaje activo.

### 1.1 Contexto inicial

- `/dev-session` ejecutado: memoria cargada, bitácora inicializada, loop de guardado activado (30 min).
- Nota: `git log` dentro del proyecto resuelve a un repo cuya raíz es el home del usuario (branch `clean_main`, commits de otro proyecto de seguros) — `english_learning` NO tiene repo git propio.

### 1.2 Análisis de brechas (app actual vs objetivo)

1. Timer solo 15/20 min fijos, sin 5 min ni valor libre
2. Quiz solo de tipeo con match exacto (frustrante: acentos, artículos) — sin opción múltiple
3. Timer y config mueren al recargar la página (setInterval sin persistencia)
4. Selección de palabras 100% aleatoria — `times_practiced`/`times_correct` se guardan pero no se usan
5. Calidad de traducciones dudosa en seed ("house"→"albergar") — declarado fuera de alcance

### 1.3 Decisiones de diseño (brainstorming con usuario)

| Pregunta | Decisión |
|---|---|
| Alcance interrupción | Ambos por fases: F1 in-app (modal), F2 notificador nativo macOS (solo gancho) |
| Tipos de pregunta | Los 4: mc_word, mc_phrase, cloze (hueco), typing tolerante |
| Selección de palabras | Ponderada por fallos (usa contadores existentes) |
| Arquitectura | B: motor en backend — `GET /api/quiz/next` + `POST /api/quiz/answer`, stateless, testeable, reutilizable por F2 |

Diseño presentado en 7 secciones (config persistente en localStorage, modal sobre cualquier tab, match tolerante, degradación con <4 palabras, primeros tests pytest del proyecto, gancho `?quiz=1` para F2). **Pendiente: aprobación del usuario → spec → plan.**

### 1.4 Archivos
- **Nuevos:** docs/BITACORA.md, docs/ARCHITECTURE.md
- **Modificados:** ninguno (aún sin código)

### 1.5 Próximo paso
Usuario aprueba/ajusta diseño → escribir spec en `docs/superpowers/specs/2026-07-14-quiz-forzado-design.md` → plan de implementación.

---

## Paso 2 · Quiz forzado implementado (2026-07-14)

**Meta:** Implementar el diseño aprobado (spec `2026-07-14-quiz-forzado-design.md`) siguiendo TDD: motor de quiz puro en backend, endpoints stateless, y frontend con config/timer persistentes + modal, sin romper la sesión de práctica existente.

### 2.1 Qué se construyó

- **Motor de quiz** (`backend/quiz.py`, sin I/O): normalización y match tolerante (acentos, artículos, sinónimos), ponderación de palabras por tasa de fallos (`word_weight`, palabra nueva = 3.0, 0% correcto = 5.0), elegibilidad de tipos de pregunta según vocabulario disponible, y armado de las 4 preguntas (`mc_word`, `mc_phrase`, `cloze`, `typing`) con distractores tomados del propio vocabulario.
- **Endpoints** (`backend/main.py`): `GET /api/quiz/next` (selección ponderada + construcción de pregunta) y `POST /api/quiz/answer` (match tolerante + actualización de `times_practiced`/`times_correct` en `words.json`); reemplazan el antiguo `/api/quiz/check`.
- **Frontend** (`frontend/index.html`): card de configuración con presets 5/10/15/30 min + campo libre, selección de tipos y dirección, persistidos en `localStorage` (`elearn_config`); timer persistente (sobrevive a recarga porque guarda `timerEndsAt` absoluto); modal de quiz forzado sobre cualquier pestaña, con gancho `?quiz=1` para forzarlo al cargar (preparado para el notificador nativo de fase 2); la sesión de práctica manual fue migrada para consumir el mismo motor (`/api/quiz/next` / `/api/quiz/answer`), eliminando lógica de preguntas duplicada.
- **Tests:** primeros tests pytest del proyecto — 21 tests en `backend/tests/test_quiz.py` (normalización/match, ponderación, elegibilidad, construcción de preguntas, endpoints).

### 2.2 Verificación — Step 1: suite completa

Comando:
```
python3 -m pytest backend/tests/ -v
```
Output real (tail):
```
backend/tests/test_quiz.py::test_quiz_next_returns_question PASSED       [ 76%]
backend/tests/test_quiz.py::test_quiz_next_empty_vocab_404 PASSED       [ 80%]
backend/tests/test_quiz.py::test_quiz_next_invalid_types_422 PASSED     [ 85%]
backend/tests/test_quiz.py::test_quiz_answer_updates_stats PASSED       [ 90%]
backend/tests/test_quiz.py::test_quiz_answer_tolerant_and_wrong PASSED  [ 95%]
backend/tests/test_quiz.py::test_quiz_answer_unknown_word_404 PASSED    [100%]

============================== 21 passed in 0.28s ==============================
```

### 2.3 Verificación — Step 2: flujo real (criterio de éxito, spec §10)

Con `./start.sh` corriendo en :8003, verificado con `curl` y `agent-browser` (headless, sin interacción humana):

1. **Pregunta válida por API:** `curl -s 'http://localhost:8003/api/quiz/next' | python3 -m json.tool` → devolvió una pregunta `cloze` bien formada (prompt con hueco, 4 opciones únicas incluyendo la respuesta correcta).
2. **Timer 1 min + modal + stats:** se fijó `cfg.intervalMin=1` y `startTimer()` vía JS eval; el countdown corrió normalmente (`01:00` → `00:55` tras unos segundos). Se disparó `fireTimerAlert()` manualmente → apareció el modal (`🎯 ¡Hora de practicar!`) con una pregunta `cloze` para la palabra "think"; se respondió correctamente y, al cerrar el modal y volver a la pestaña Vocabulario, la card de "think" pasó de `Practicado 4×` a `Practicado 5× · 100% correcto` — confirmado también contra `data/words.json` (times_practiced 4→5).
3. **Recarga con timer corriendo:** se recargó la página con el timer activo; tras volver a la pestaña Práctica el estado mostraba "Activo" y el countdown seguía corriendo (`00:43`, no reseteado a `--:--`).
4. **Gancho `?quiz=1`:** al abrir `http://localhost:8003/?quiz=1` el modal apareció inmediatamente con una pregunta (`mc_word`, "house" → español), sin necesidad de esperar el timer.
5. **Ponderación por fallos:** se falló la palabra "beautiful" 3 veces seguidas vía `POST /api/quiz/answer` (respuestas incorrectas), quedando en `times_practiced=4, times_correct=1` (25% correcto → peso `1 + 4×(1-0.25) = 4.0`, el más alto del vocabulario). Se consultó `GET /api/quiz/next?types=mc_word` 20 veces seguidas y "beautiful" salió **11/20** (55%), muy por encima de las demás palabras (3/20 cada una) — confirma que la selección ponderada la prioriza. `data/words.json` se restauró a su estado previo a esta prueba tras verificar (los cambios de test no se commitean).

### 2.4 Archivos

- **Nuevos:** `backend/quiz.py`, `backend/tests/__init__.py`, `backend/tests/test_quiz.py`, `requirements-dev.txt`
- **Modificados:** `backend/main.py` (endpoints quiz), `frontend/index.html` (config, timer, modal, sesión migrada), `docs/ARCHITECTURE.md`, `docs/BITACORA.md`

### 2.5 Próximo paso

Fase 2 — notificador nativo macOS (launchd + osascript), gancho `?quiz=1` listo.
