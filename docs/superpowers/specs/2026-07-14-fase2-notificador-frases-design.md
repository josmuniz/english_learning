# Spec: Fase 2 — Notificador nativo macOS + Frases

**Fecha:** 2026-07-14
**Estado:** Aprobado por el usuario (diseño validado en brainstorming)
**Depende de:** Fase 1 mergeada (`1c66cee`) — motor de quiz, `GET /api/quiz/next`, `POST /api/quiz/answer`, gancho `?quiz=1`.

## 1. Problema

La fase 1 solo interrumpe con la pestaña del navegador abierta. El usuario quiere ser interrumpido **aunque el navegador esté cerrado**, responder el quiz sin fricción, y además poder registrar **frases multi-palabra** ("break the ice") — hoy `POST /api/words` falla con frases porque dictionaryapi.dev solo resuelve palabras sueltas.

Hallazgo que condicionó el diseño: `osascript display notification` NO ejecuta acciones al click (no puede abrir URLs), y `terminal-notifier` no está instalado. Decisión del usuario: **el diálogo AppleScript ES el quiz** — se responde ahí mismo, sin navegador.

## 2. Objetivos

1. Frases multi-palabra como vocabulario, ingresables desde la web y desde el diálogo nativo.
2. Diálogo nativo cada N minutos que muestra la pregunta y acepta la respuesta (opción múltiple y escritura), actualizando stats vía la API existente.
3. Botón "+ Agregar" en el diálogo de resultado para capturar vocabulario al vuelo.
4. Backend siempre disponible: launchd lo arranca al login y lo resucita si muere.
5. Instalador/desinstalador de un comando con intervalo configurable (default 5 min).

**No-objetivos:** configurar tipos/dirección del notificador (usa los defaults del endpoint: todos los tipos, `both`) · pausas horarias / no-molestar · icono o branding del diálogo · sincronizar el intervalo del notificador con el de la web (son independientes) · cambios al motor de quiz (la fase 1 ya soporta ítems sin ejemplo).

## 3. Componente A — Frases como vocabulario

### 3.1 Backend (`backend/main.py`, `add_word`)

- Detección: tras `strip().lower()`, si la entrada contiene espacios internos → es frase.
- Camino frase: NO llama `fetch_dictionary` ni Datamuse. Solo `translate(frase)` (MyMemory traduce frases). Campos:
  - `type: "phrase"` · `word_es: traducción o la frase misma si translate falla` (mismo fallback actual `word_es or word`)
  - `ipa`, `pronunciation_es`, `synonym_en/es`, `antonym_en/es`, `definition_en/es`, `example_en/es`: todos `""`
  - resto del registro idéntico (id, created_at, contadores). **El esquema de words.json NO cambia.**
- Validación: entrada máx. 80 caracteres (400 si excede). El chequeo de duplicados existente (case-insensitive sobre `word_en`) aplica igual.
- El camino palabra-sola queda EXACTAMENTE como está.

### 3.2 Motor de quiz — sin cambios (verificado por diseño)

Un ítem frase tiene `example_en == ""` → `eligible_types` ya lo excluye de `cloze`/`mc_phrase`; participa en `mc_word` (prompt = la frase, opciones = traducciones) y `typing`. Como donante de distractores para `mc_phrase`, `_has_examples` ya lo filtra. Se agregan tests que fijan este comportamiento (§7).

### 3.3 Web (`frontend/index.html`)

- Placeholder del input: `"Ej: perseverance, break the ice…"`; texto de ayuda de la card menciona frases.
- La card de una frase se ve igual (campos vacíos ya se renderizan con `—` o se omiten).

## 4. Componente B — Diálogo nativo (`notifier/quiz_dialog.py`)

Python 3 stdlib únicamente (`urllib.request`, `json`, `subprocess`, `pathlib`). Sin dependencias nuevas.

### 4.1 Flujo por ciclo

```
lockfile? (fresco <10 min) → salir 0 (ciclo anterior aún abierto)
GET http://localhost:8003/api/quiz/next  (timeout 5s)
  ├─ error de red / backend caído → log + salir 0 (silencioso; launchd lo está resucitando)
  └─ 200 → según type:
       options presentes → choose from list (4 opciones, prompt = etiqueta + pregunta + hint)
       typing           → display dialog con campo de texto, botones {Saltar, Responder}
     Cancelar/Saltar → log "skipped" + salir 0 (NO postea — no penaliza stats)
     Respuesta → POST /api/quiz/answer
       → display dialog resultado: "✅ ¡Correcto! — <correct_answer>" o "❌ Incorrecto. Era: <correct_answer>"
         botones {OK, + Agregar}, default OK, con timeout (giving up after 60)
         └─ "+ Agregar" → display dialog input "Nueva palabra o frase en inglés:"
              → POST /api/words → diálogo confirmación "✓ <word_en> → <word_es>"
              → error (409 duplicada / 404 no encontrada / red) → diálogo con el detail del error
```

### 4.2 Detalles técnicos

- **Etiquetas de pregunta**: mismas de la web (`¿Cómo se dice en inglés?` / `¿Qué significa en español?` / `Completa la frase:` / etc.), derivadas de `type`+`direction` del payload.
- **Escapado AppleScript**: toda cadena interpolada en el script pasa por `applescript_escape(s)` = `\` → `\\` y `"` → `\"`. Las opciones se pasan como lista AppleScript construida elemento a elemento escapado.
- **Parsing de resultados osascript**: `choose from list` devuelve la opción o `false` (cancel); `display dialog` devuelve `button returned:X` y `text returned:Y` (parse por prefijos, tolerante a comas en el texto: split solo en `, text returned:` la primera vez).
- **Lockfile**: `/tmp/elearn-quiz.lock` con mtime; si existe y tiene <10 min, salir; si es más viejo, sobreescribir y continuar. Se borra al terminar (try/finally).
- **Timeout del diálogo de pregunta**: `choose from list` no soporta timeout nativo → lo cubre el lockfile (un diálogo ignorado bloquea como máximo el ciclo actual; el siguiente ciclo tras 10 min lo ignora y muestra uno nuevo — el viejo queda huérfano hasta que el usuario lo cierre; aceptable). `display dialog` (typing y resultado) usa `giving up after 60`.
- **Log**: append a `~/Library/Logs/elearn-quiz.log`, una línea por evento: `ISO8601 | ok/skip/error | detalle`. Sin datos sensibles.
- **Estructura del módulo** (para testear sin GUI): funciones puras `build_question_dialog(q) -> str`, `build_result_dialog(res) -> str`, `parse_dialog_output(raw) -> dict`, `applescript_escape(s)`; capa I/O `run_osascript(script) -> str` y `api(method, path, body=None)` — solo estas dos se mockean en tests. `main()` orquesta.

## 5. Componente C — launchd + instalador (`notifier/install.sh`)

- **`com.josemuniz.elearn-backend.plist`**: `ProgramArguments` = [`/bin/bash`, `<ABS>/start.sh`], `WorkingDirectory` = raíz del proyecto, `RunAtLoad` = true, `KeepAlive` = true, stdout/err → `~/Library/Logs/elearn-backend.log`.
- **`com.josemuniz.elearn-quiz.plist`**: `ProgramArguments` = [`/usr/bin/python3`, `<ABS>/notifier/quiz_dialog.py`], `StartInterval` = N×60, `RunAtLoad` = false.
- **`install.sh [minutos]`** (default 5, rango 1-120): genera ambos plists (heredoc con rutas absolutas calculadas desde la ubicación del script), los copia a `~/Library/LaunchAgents/`, `launchctl unload` previo silencioso + `launchctl load`. Imprime estado y cómo ver logs.
- **`install.sh --uninstall`**: `launchctl unload` ambos + borra los plists. No toca logs ni datos.
- Los LaunchAgents corren en la sesión GUI del usuario → osascript puede mostrar diálogos (mismo patrón que los `com.fxbot.*` existentes).

## 6. Convivencia con el timer web

Independientes por diseño: el notificador corre siempre (launchd); el timer web solo si se activa en la pestaña. Recomendación documentada en BITACORA/ARCHITECTURE: con el notificador instalado, dejar el timer web desactivado para no duplicar interrupciones. (El guard de fase 1 ya evita que el timer web interrumpa una sesión de práctica activa; el diálogo nativo no tiene visibilidad de la pestaña y no se coordina con ella — aceptado.)

## 7. Tests (pytest, extienden los 23 existentes)

**Frases (`backend/tests/test_words.py`, nuevo):** con `translate` y `fetch_dictionary` mockeados (monkeypatch sobre `backend.main`):
1. POST frase → 200, `type=="phrase"`, `word_es` = traducción mock, `example_en==""`, NO llamó `fetch_dictionary`.
2. POST frase con translate fallando → `word_es` = la frase misma.
3. POST >80 chars → 400. POST frase duplicada → 409.
4. Palabra sola sigue usando el camino dictionary (mock llamado).
5. Motor: ítem frase nunca genera `cloze`/`mc_phrase` (`eligible_types`), y aparece como opción válida en `mc_word`.

**Notificador (`backend/tests/test_notifier.py`, nuevo; importa `notifier.quiz_dialog`):**
6. `applescript_escape`: comillas y backslashes.
7. `build_question_dialog` MC: contiene las 4 opciones escapadas y la etiqueta correcta; typing: `default answer` presente.
8. `parse_dialog_output`: `false` → None; `button returned:Responder, text returned:hola, mundo` → texto completo `hola, mundo`; `button returned:Saltar` → skip.
9. `main()` con `api` mockeado lanzando URLError → retorna 0 sin invocar `run_osascript`.
10. Flujo completo mockeado: pregunta MC → respuesta → POST con body correcto → diálogo resultado; "+ Agregar" → POST /api/words.

Correr: `python3 -m pytest backend/tests/ -v` (esperado: 23 + ~10 nuevos).

## 8. Criterio de éxito

1. `curl -X POST /api/words` con `{"word": "break the ice"}` crea la frase traducida; visible en la web; sale en quizzes `mc_word`/`typing`.
2. `./notifier/install.sh 5` instala ambos agentes; `launchctl list | grep elearn` los muestra.
3. Cada 5 min aparece el diálogo nativo con una pregunta; responder actualiza `times_practiced` en words.json; Cancelar no penaliza.
4. "+ Agregar" desde el diálogo crea vocabulario visible en la web.
5. Matar el proceso uvicorn → launchd lo resucita (verificable en segundos).
6. `./notifier/install.sh --uninstall` deja `launchctl list` sin agentes elearn.
7. Suite pytest completa verde.

## 9. Riesgos y bordes

| Riesgo | Mitigación |
|---|---|
| Diálogo ignorado bloquea ciclos | Lockfile con staleness 10 min + `giving up after 60` donde AppleScript lo soporta |
| Backend caído al disparar | Salir silencioso; KeepAlive lo resucita |
| Frase con comillas/acentos rompe AppleScript | `applescript_escape` en toda interpolación (test 6) |
| MyMemory rate-limit al agregar frases | Mismo comportamiento actual de palabras (fallback a la entrada); documentado |
| Doble interrupción web+nativo | Documentado §6: timer web off con notificador instalado |
| launchd corre antes del login GUI | LaunchAgents (no Daemons) — solo corren en sesión de usuario |
