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

---

## Paso 3 · Fase 2: frases + notificador nativo (2026-07-14)

**Meta:** Implementar el diseño aprobado (spec `2026-07-14-fase2-notificador-frases-design.md`): vocabulario multi-palabra (frases) y un notificador nativo macOS que dispare el quiz aunque el navegador esté cerrado, con backend siempre vivo bajo launchd.

### 3.1 Qué se construyó

- **Frases como vocabulario** (`backend/main.py`, `add_word`): entrada con espacios internos → `type: "phrase"`, salta `fetch_dictionary`/Datamuse y solo traduce vía `translate()` (fallback a la frase misma si MyMemory falla); resto de campos derivados (`ipa`, `example_en`, etc.) quedan `""` — el esquema de `words.json` no cambia. Validación de 80 caracteres y duplicados aplica igual que a palabras sueltas. El motor de quiz no necesitó cambios: un ítem sin `example_en` ya queda fuera de `cloze`/`mc_phrase` por `eligible_types` y participa normalmente en `mc_word`/`typing`.
- **Notificador** (`notifier/quiz_dialog.py`): módulo separado en funciones puras (`applescript_escape`, `build_question_dialog`, `build_result_dialog`, `parse_dialog_output`) y capa I/O (`run_osascript`, `api`) para poder testear sin GUI. `main()` orquesta: lockfile (`/tmp/elearn-quiz.lock`, staleness 10 min) → `GET /api/quiz/next` → diálogo AppleScript (`choose from list` para opción múltiple, `display dialog` con campo de texto para typing) → `POST /api/quiz/answer` → diálogo de resultado con botón "+ Agregar" → `POST /api/words`. Silencioso (exit 0) si el backend está caído o si el diálogo anterior sigue abierto.
- **`notifier/install.sh`**: genera y (re)instala dos LaunchAgents en `~/Library/LaunchAgents/` — `com.josemuniz.elearn-backend` (`start.sh`, `KeepAlive`, `RunAtLoad`) y `com.josemuniz.elearn-quiz` (`quiz_dialog.py`, `StartInterval` = N×60 seg, default 5 min, rango 1-120). `install.sh --uninstall` descarga ambos y borra los plists sin tocar logs ni datos.
- **`start.sh` (patch de Task 4):** launchd corre con un PATH mínimo que resuelve `python3` al intérprete de sistema de Apple (sin `uvicorn`/`fastapi`). El script ahora prueba el `python3` del PATH y, si no tiene las deps, cae al `anaconda3` que sí las tiene; si ninguno sirve, falla ruidoso (`exit 1` con mensaje) en vez de arrancar silenciosamente con el intérprete equivocado.
- **Tests:** 17 tests nuevos — `backend/tests/test_words.py` (6: frase traducida, fallback de traducción, límite de 80 chars, duplicado 409, palabra sola sigue usando dictionary, elegibilidad de tipos) y `backend/tests/test_notifier.py` (11: escapado AppleScript, construcción de diálogos MC/typing, parseo de `choose from list`/`display dialog`, backend caído sale silencioso, lockfile fresco se salta, flujo completo mockeado pregunta→respuesta→POST, skip no penaliza).

### 3.2 Verificación — Step 1: suite completa

Comando:
```
python3 -m pytest backend/tests/ -v
```
Output real (tail):
```
backend/tests/test_words.py::test_add_phrase_skips_dictionary PASSED     [ 87%]
backend/tests/test_words.py::test_add_phrase_translate_fallback PASSED   [ 90%]
backend/tests/test_words.py::test_add_word_too_long_400 PASSED           [ 92%]
backend/tests/test_words.py::test_add_phrase_duplicate_409 PASSED        [ 95%]
backend/tests/test_words.py::test_single_word_still_uses_dictionary PASSED [ 97%]
backend/tests/test_words.py::test_phrase_only_eligible_for_mc_word_and_typing PASSED [100%]

============================== 40 passed in 0.41s ==============================
```

### 3.3 Verificación — Step 2: criterios de éxito del spec §8 (automatizables)

1. **Frase real de punta a punta:** con `./start.sh` corriendo, `POST /api/words {"word": "see you later"}` → `200`, `type: "phrase"`, `word_es: "¡hasta luego"` (traducida por MyMemory, no fallback). Se consultó `GET /api/quiz/next?types=mc_word` 20 veces seguidas: la frase apareció como **prompt** (`"prompt": "see you later"`, dirección `en_to_es`, y también como prompt en español pidiendo la traducción al inglés) y como **opción distractora** en preguntas de otras palabras — confirma que participa del motor sin cambios. La frase de prueba se deja en el vocabulario (indicado por el brief).
2. **LaunchAgents instalados:** `launchctl list | grep elearn` → 2 líneas (`com.josemuniz.elearn-quiz`, `com.josemuniz.elearn-backend`).
3. **KeepAlive:** ya verificado en Task 4 Step 4 (matar el proceso uvicorn → launchd lo resucita en segundos).
4. **Uninstall + reinstall:**
   ```
   ./notifier/install.sh --uninstall && launchctl list | grep elearn; echo "exit=$?"
   ```
   Output: `✓ Agentes elearn desinstalados`, sin líneas de `grep`, `exit=1` (no-match). Reinstalado de inmediato con `./notifier/install.sh 5` → `✓ Backend: com.josemuniz.elearn-backend (KeepAlive, ...)` / `✓ Quiz: com.josemuniz.elearn-quiz cada 5 min (...)`; `launchctl list | grep elearn` volvió a mostrar los 2 agentes (backend con PID nuevo, confirmando `RunAtLoad`) y `curl http://localhost:8003/api/words` respondió `200` tras el reinstall. **Estado final: instalado, intervalo 5 min** (el entregable queda así).
5. **Criterios interactivos** (responder el diálogo real, "+ Agregar" desde el diálogo): pendiente validación interactiva del usuario — no automatizables sin GUI real.

### 3.4 Archivos

- **Nuevos:** `notifier/quiz_dialog.py`, `notifier/install.sh`, `notifier/__init__.py`, `backend/tests/test_words.py`, `backend/tests/test_notifier.py`
- **Modificados:** `backend/main.py` (`add_word` con camino de frases), `frontend/index.html` (placeholder/ayuda mencionan frases), `start.sh` (resolución de python fail-loud), `docs/ARCHITECTURE.md`, `docs/BITACORA.md`

### 3.5 Próximo paso

Validación interactiva del usuario (responder un diálogo real disparado por launchd, probar "+ Agregar" con una frase nueva desde el diálogo) + revisión global de rama antes de merge. Follow-up pendiente de fase 1 (fuera de este plan): aplicar `esc()` en `renderWords()`.

---

## Paso 4 · Alta bilingüe ES/EN (2026-07-14)

**Meta:** Implementar el diseño aprobado (spec `2026-07-14-alta-bilingue-design.md`): permitir agregar vocabulario partiendo de una palabra o frase en español (además de inglés), reutilizando el mismo pipeline de enriquecimiento.

### 4.1 Qué se construyó

- **Backend** (`backend/main.py`, `POST /api/words`): nuevo campo `lang: "en" | "es"` en `WordRequest` (default `"en"`, 422 si viene otro valor). Con `lang="es"`, la entrada se traduce primero ES→EN (`translate()`, dirección invertida) y el resultado alimenta el mismo pipeline que ya enriquecía palabras en inglés, ahora extraído a `_build_english_entry()` — evita duplicar la lógica de `dictionaryapi.dev` + Datamuse + `ipa_to_spanish` entre los dos caminos (en/es). El dedup (`test_dedup_by_word_es`) sigue bloqueando en ambos sentidos.
- **Web** (`frontend/index.html`): toggle EN/ES en el formulario de alta con placeholder dinámico según el idioma elegido.
- **Diálogo nativo** (`notifier/quiz_dialog.py`): paso de idioma (Español/Inglés) antes de pedir el texto en el flujo "+ Agregar"; `Cancelar` aborta sin llamar a `POST /api/words`.
- **Tests:** 7 tests nuevos (40 → 47) — alta de palabra española vía pipeline inglés, alta de frase española invertida, fallo de traducción → 400, dedup por `word_es`, validación de `lang` inválido/default, y el flujo de diálogo con paso de idioma (confirmar Español y cancelar).

### 4.2 Verificación — Step 1: suite completa

Comando:
```
python3 -m pytest backend/tests/ -v
```
Output real (tail):
```
backend/tests/test_words.py::test_add_spanish_word_enriched_via_english_pipeline PASSED [ 91%]
backend/tests/test_words.py::test_add_spanish_phrase_inverted PASSED     [ 93%]
backend/tests/test_words.py::test_add_spanish_translate_fails_400 PASSED [ 95%]
backend/tests/test_words.py::test_dedup_by_word_es PASSED                [ 97%]
backend/tests/test_words.py::test_lang_invalid_422_and_default_en PASSED [100%]

============================== 47 passed in 0.44s ==============================
```

### 4.3 Verificación — Step 2: criterios de éxito del spec §7 (automatizables)

Con `./start.sh` corriendo en :8003 (launchd, KeepAlive):

1. **Web con 🇪🇸, card rica:** `curl -s -X POST http://localhost:8003/api/words -H 'Content-Type: application/json' -d '{"word": "tiburón", "lang": "es"}'` → **409** (`"Esa palabra ya está en tu vocabulario"`) porque la verificación en navegador de Task 2 ya había agregado "tiburón" al vocabulario real — evidencia válida del criterio 4 (dedup), no del alta fresca. Para el alta fresca se usó una palabra distinta, `"ballena"`:
   ```
   curl -s -X POST http://localhost:8003/api/words -H 'Content-Type: application/json' -d '{"word": "ballena", "lang": "es"}' | python3 -m json.tool
   ```
   → `200`, `word_es: "ballena"`, `word_en: "whale"`, card rica (`type: "noun"`, `ipa: "/weɪl/"`, `definition_en`/`definition_es`, `example_en: "The whale was remarkable."`, `example_es: "La ballena era notable."`). Se deja en el vocabulario (indicado por el brief).
2. **Duplicados bloqueados:** repetir el mismo POST de `"tiburón"` y luego de `"ballena"` → ambos **409** (`"Esa palabra ya está en tu vocabulario"`), confirmando dedup en el sentido español.
3. **`lang` inválido → 422:** `curl -s -X POST http://localhost:8003/api/words -H 'Content-Type: application/json' -d '{"word": "strong", "lang": "fr"}'` → **422**, `{"detail": "lang inválido (en|es)"}`.
4. **Diálogo nativo con paso de idioma** ("+ Agregar" → Español → "tiburón" → confirma `shark → tiburón`): criterio interactivo, no automatizable sin GUI real — pendiente validación del usuario.

### 4.4 Archivos

- **Modificados:** `backend/main.py` (`lang` en `WordRequest`, `_build_english_entry()` compartido, validación 422), `frontend/index.html` (toggle EN/ES + placeholder dinámico), `notifier/quiz_dialog.py` (paso de idioma en "+ Agregar"), `backend/tests/test_words.py`, `backend/tests/test_notifier.py`, `docs/ARCHITECTURE.md`, `docs/BITACORA.md`

### 4.5 Próximo paso

Validación interactiva del usuario (diálogo real "+ Agregar" → Español → palabra nueva) + revisión global de rama y de seguridad antes de merge a `main`. Follow-up pendiente de fase 1 (fuera de este plan): aplicar `esc()` en `renderWords()`.

---

## Paso 5 · Documento integral de la solución (2026-07-15)

**Meta:** Escribir un documento único con el diseño de la solución, su implementación, su instalación y cómo probarla.

### 5.1 Qué se hizo

Se creó `docs/SOLUCION.md` (nuevo) consolidando: diseño (visión, componentes, diagrama de arquitectura, 3 flujos, decisiones), implementación (tabla de endpoints, pipelines de alta bilingüe, motor de quiz, frontend, notificador, launchd), instalación (básica web y completa macOS con `notifier/install.sh`, desinstalación) y pruebas (suite pytest, curls funcionales, checklist web, prueba interactiva del diálogo, troubleshooting). Se verificó que el comando de tests documentado funciona: `python3 -m pytest backend/tests/ -q` → **47 passed in 0.49s**.

### 5.2 Archivos

- **Nuevos:** `docs/SOLUCION.md`
- **Modificados:** `docs/BITACORA.md`

### 5.3 Contexto inicial de la sesión

- Rama `main`, con `feature/alta-bilingue` ya mergeada (commit `ecfd236`).
- Cambio sin commitear al abrir la sesión: `data/words.json` (+228 líneas) — vocabulario agregado por uso real de la app (incluye "ballena"/"tiburón" de la verificación del Paso 4).
- Pendientes heredados del Paso 4: validación interactiva del diálogo "+ Agregar" → Español, y follow-up `esc()` en `renderWords()`.

---

## Paso 6 · Grilla editable + ejemplos cortos (2026-07-17)

**Meta:** Vista de grilla tipo planilla con edición inline (pronunciación, sinónimos, antónimos, ejemplos) y ejemplos ≤10 palabras al generar.

### 6.1 Qué se hizo

- `PATCH /api/words/{id}` con lista blanca Pydantic de 8 campos editables (`pronunciation_es`, `ipa`, sinónimo/antónimo/ejemplo EN+ES); ejemplos >10 palabras → 422 `"El ejemplo no puede superar 10 palabras"`; campos protegidos (stats, word_en/es, type) se ignoran por diseño.
- `pick_example()`: el pipeline de diccionario prefiere el primer ejemplo con ≤10 palabras; si ninguno cumple, recorta a 10 + "…".
- Frontend: tabla `Inglés|Sonido|Español|Sinónimo|Antónimo|Ejemplo|acciones` reemplaza las tarjetas; edición inline por fila (una a la vez); frases solo editan sonido/IPA (celdas restantes en "—"); errores del PATCH se muestran en la fila sin perder lo tecleado; `esc()` aplicado a toda interpolación (cierra el follow-up XSS de fase 1) y `speakById()` elimina la interpolación de texto en `onclick`.
- Ejecutado con subagent-driven development: 3 tasks implementadas con TDD (RED→GREEN), review por task, review final de rama (opus) + security review: **PASS**, ready to merge.

### 6.2 Demo

**URL:** http://localhost:8003
**Acciones de browser:**
1. Abrir la app → la sección de palabras muestra la grilla con 7 columnas
2. Click ✏️ en una frase sin pronunciación → solo 2 inputs (sonido, IPA)
3. Escribir la pronunciación → 💾 → fila actualizada + toast "Cambios guardados"
4. Recargar → persiste

**Comando terminal:**
```bash
curl -s -X PATCH http://localhost:8003/api/words/<id> \
  -H 'Content-Type: application/json' -d '{"pronunciation_es": "si yu leiter"}'
```

### 6.3 Archivos

- **Nuevos:** `backend/tests/test_edit.py`
- **Modificados:** `backend/main.py`, `backend/tests/test_words.py`, `frontend/index.html`

### 6.4 Tests

`python3 -m pytest backend/tests/ -q` → **60 passed** (47 previos + 9 PATCH + 4 pick_example; el plan estimaba 61 por un error aritmético). Verificación browser (Playwright): 7/7 checks OK, sin errores de consola; verificado además que la tabla scrollea dentro de su contenedor a 390px (el overflow lateral de la barra de tabs es pre-existente, anotado como follow-up).

### 6.5 Próximo paso

Validación interactiva del diálogo "+ Agregar" → Español (pendiente heredado). Follow-ups cosméticos anotados: CSS muerto `.word-card`/`.highlight`, label a11y del th de acciones, overflow móvil de tabs.
