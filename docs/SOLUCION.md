# English Learning App — Diseño, Implementación, Instalación y Pruebas

**Stack:** FastAPI + Uvicorn · HTML/CSS/JS vanilla · JSON plano · Python stdlib + osascript + launchd (macOS)
**Puerto:** 8003 · **Documentos relacionados:** [ARCHITECTURE.md](ARCHITECTURE.md), [BITACORA.md](BITACORA.md)

---

## 1. Diseño de la solución

### 1.1 Problema y visión

App **local y personal** para construir vocabulario inglés↔español. El usuario agrega palabras o frases (en inglés **o en español**), el sistema las enriquece automáticamente (definición, IPA, fonética española, traducción, sinónimo/antónimo, ejemplo) y luego lo obliga a practicar mediante quizzes: en la web y mediante **diálogos nativos de macOS que aparecen cada N minutos** aunque el navegador esté cerrado.

### 1.2 Componentes

| Componente | Tecnología | Ubicación | Rol |
|---|---|---|---|
| Frontend | HTML/CSS/JS vanilla single-file | `frontend/index.html` | Alta de vocabulario, listado, práctica con modal, timer configurable |
| Backend API | FastAPI + Uvicorn | `backend/main.py` | Enriquecimiento, persistencia, motor de quiz vía REST; sirve el frontend como estático |
| Motor de quiz | Python puro (sin I/O) | `backend/quiz.py` | Selección ponderada, 4 tipos de pregunta, distractores, match tolerante |
| Storage | JSON plano | `data/words.json` | Vocabulario + estadísticas de práctica |
| Notificador nativo | Python stdlib + osascript | `notifier/quiz_dialog.py` | Quiz forzado en diálogo AppleScript, disparado por launchd |
| Instalador | Bash + launchd | `notifier/install.sh` | LaunchAgents: backend siempre vivo + quiz periódico |
| Arranque | Bash | `start.sh` | Resolución robusta de python3 y arranque de uvicorn |

### 1.3 Arquitectura y flujos

```
                       ┌──────────────────────────────┐
                       │   APIs públicas (sin key)     │
                       │  dictionaryapi.dev (dic/IPA)  │
                       │  mymemory (traducción EN↔ES)  │
                       │  datamuse (sinón./antón.)     │
                       └──────────────▲───────────────┘
                                      │ httpx (paralelo)
┌────────────────┐   HTTP   ┌─────────┴────────┐  read/write  ┌────────────────┐
│ frontend/       │◄────────►│ backend/main.py  │◄────────────►│ data/words.json │
│ index.html      │  :8003   │ (FastAPI)        │              └────────────────┘
└────────────────┘          │  + backend/quiz.py│
                            └─────────▲────────┘
┌─────────────────────────┐  urllib   │
│ launchd                  │──────────┘
│ · elearn-backend (KeepAlive → start.sh)
│ · elearn-quiz (StartInterval → notifier/quiz_dialog.py → osascript)
└─────────────────────────┘
```

**Flujo 1 — Alta bilingüe de vocabulario:**

```
Usuario escribe palabra o frase + idioma (en|es)
  → POST /api/words {word, lang}
    lang="es" → translate ES→EN primero (MyMemory); si falla → 400
    dedup contra word_en Y word_es (409 si ya existe)
    con espacios → camino frase (solo traducción)
    sin espacios → pipeline inglés completo:
        dictionaryapi.dev (definición, IPA, ejemplo, tipo)
        + traducciones y Datamuse en paralelo (asyncio.gather)
        + ipa_to_spanish() → fonética legible en español
  → append a data/words.json → card completa al cliente
```

**Flujo 2 — Quiz web:**

```
Timer del frontend (persistente en localStorage)
  → GET /api/quiz/next  (tipos/dirección configurables)
  → modal de pregunta → POST /api/quiz/answer (match tolerante)
  → actualiza times_practiced/times_correct en words.json
```

**Flujo 3 — Quiz forzado nativo (macOS):**

```
launchd (com.josemuniz.elearn-quiz, cada N min)
  → notifier/quiz_dialog.py (lock anti-solape en /tmp/elearn-quiz.lock)
  → GET /api/quiz/next → diálogo AppleScript (choose from list / display dialog)
  → POST /api/quiz/answer → resultado ✓/✗ con botón "+ Agregar"
      → "+ Agregar" pregunta idioma (Español/Inglés) → texto → POST /api/words
launchd (com.josemuniz.elearn-backend, KeepAlive) mantiene el backend :8003 vivo
```

### 1.4 Decisiones de diseño

- **Sin base de datos:** volumen personal pequeño (decenas de palabras); `words.json` completo se relee y reescribe por operación. Simplicidad > rendimiento.
- **APIs gratuitas sin API key:** dictionaryapi.dev, MyMemory y Datamuse no requieren autenticación (MyMemory tiene rate limit diario por IP). Los fallos de servicios secundarios degradan a campos vacíos, nunca rompen el alta.
- **Fonética española propia:** mapa IPA→grafemas españoles (`_IPA_MAP`); los dígrafos se procesan antes que los símbolos simples porque el orden de reemplazo importa (`tʃ`→`ch` antes que `t`).
- **Motor de quiz puro:** `backend/quiz.py` no hace I/O; recibe y devuelve estructuras. Esto lo hace testeable de forma determinista (se inyecta `rng`).
- **Notificador solo stdlib:** `quiz_dialog.py` no depende de pip (urllib + subprocess + osascript), porque launchd lo ejecuta con el python3 del sistema.
- **Alta bilingüe reutilizando el pipeline:** la entrada en español se traduce a inglés y alimenta el mismo `_build_english_entry()` que el camino inglés — una sola fuente de verdad para el enriquecimiento.

---

## 2. Implementación

### 2.1 Backend — API REST (`backend/main.py`)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/words` | Alta con enriquecimiento. Body: `{word, lang: "en"\|"es"}` (default `en`). Errores: 400 vacía/>80 chars/traducción ES fallida, 409 duplicada, 404 no está en diccionario, 422 `lang` inválido |
| GET | `/api/words` | Lista completa del vocabulario |
| DELETE | `/api/words/{id}` | Elimina una entrada (404 si no existe) |
| POST | `/api/validate` | Valida heurísticamente una oración escrita con la palabra (puntaje 0-100) |
| GET | `/api/quiz/next` | Próxima pregunta. Query: `types` (csv de `mc_word,mc_phrase,cloze,typing`), `direction` (`es_to_en\|en_to_es\|both`) |
| POST | `/api/quiz/answer` | Corrige y actualiza estadísticas. Body: `{word_id, type, direction, answer}` |
| GET | `/` | Frontend estático (`StaticFiles`, montado al final) |

Piezas clave:

- **`_build_english_entry(word_en, words, word_es_override=None)`** — pipeline inglés completo: `fetch_dictionary()` y luego, **en paralelo** (`asyncio.gather`), traducción de palabra/definición/ejemplo + sinónimo/antónimo de Datamuse; después traduce sinónimo/antónimo a español. Construye la card y persiste.
- **`_add_from_spanish(entry_es, words)`** — traduce ES→EN; si el resultado tiene espacios va al camino frase, si no al pipeline inglés con `word_es_override` (se conserva lo que escribió el usuario).
- **`_add_phrase(word_en, word_es, words)`** — camino frase: solo traducción, card con campos de diccionario vacíos y `type: "phrase"`.
- **`_is_duplicate(entry, words)`** — dedup case-insensitive contra `word_en` y `word_es`.
- **`ipa_to_spanish(ipa)`** — aproximación fonética española a partir del IPA.

Esquema de una entrada en `data/words.json`:

```json
{
  "id": "uuid", "created_at": "ISO-8601",
  "word_en": "whale", "word_es": "ballena",
  "type": "noun", "ipa": "/weɪl/", "pronunciation_es": "weil",
  "synonym_en": "…", "synonym_es": "…", "antonym_en": "…", "antonym_es": "…",
  "definition_en": "…", "definition_es": "…",
  "example_en": "…", "example_es": "…",
  "times_practiced": 0, "times_correct": 0
}
```

### 2.2 Motor de quiz (`backend/quiz.py`)

- **Selección ponderada por fallos:** `word_weight()` — palabra nunca practicada pesa 3.0; el resto `1 + 4·(1 − aciertos/prácticas)`, así lo que más fallas aparece más.
- **4 tipos de pregunta** con elegibilidad por datos disponibles (`eligible_types`): `mc_word` (opción múltiple palabra), `mc_phrase` (opción múltiple frase, requiere ejemplos en ≥4 entradas), `cloze` (completar hueco en el ejemplo), `typing` (escribir la traducción; único tipo posible con <4 palabras).
- **Distractores del propio vocabulario:** `pick_distractors()` toma 3 entradas distintas (con ejemplo si el tipo lo exige).
- **Match tolerante:** `normalize()` — case-insensitive, sin acentos (NFD), sin artículos (`el/la/the/a…`), espacios colapsados; acepta también el sinónimo como respuesta válida.

### 2.3 Frontend (`frontend/index.html`, single-file)

- Tabs de vocabulario y práctica (`switchTab`), tema claro/oscuro (`toggleTheme`), TTS del navegador (`speak`).
- Alta con **toggle EN/ES** (`setAddLang`) y placeholder dinámico; cards renderizadas por `renderWords()`.
- Práctica: modal de quiz (`openQuizModal`/`renderQuestion`/`sendAnswer`), configuración de tipos/dirección persistida (`saveConfig`), paso extra de escribir una oración (`submitSentence` → `/api/validate`).
- Timer configurable persistente en `localStorage` (`startTimer`/`rearmTimer`) con alerta (`fireTimerAlert`). Recomendación: con el notificador nativo instalado, dejar el timer web desactivado.

### 2.4 Notificador nativo (`notifier/quiz_dialog.py`)

Separación en tres capas para testeabilidad sin GUI:

- **Helpers puros:** construcción de scripts AppleScript (`build_question_dialog`, `build_result_dialog`, `build_add_lang_dialog`, `build_add_dialog`) y parsing del output de `osascript` (`parse_dialog_output` — botones, texto, `gave up`, cancelaciones).
- **Capa I/O:** `api()` (urllib contra :8003), `run_osascript()`, `log()` a `~/Library/Logs/elearn-quiz.log`, `acquire_lock()` (lock en `/tmp/elearn-quiz.lock`, stale a los 600 s, evita diálogos solapados).
- **Orquestación:** `main()` — pregunta → respuesta → resultado; el botón `+ Agregar` dispara `offer_add_word()`: idioma (Español/Inglés) → texto → `POST /api/words` → confirmación `word_en → word_es`. Backend caído o cancelación degradan silenciosamente (log y exit 0, sin diálogo de error intrusivo).

### 2.5 Arranque e infraestructura

- **`start.sh`:** idempotente (si :8003 ya responde, sale). Resuelve un `python3` que tenga `uvicorn+fastapi` (primero el del PATH — respeta venvs —, luego fallback a `/opt/anaconda3/bin/python3`) porque launchd corre con PATH mínimo que resuelve al python de Apple sin dependencias. Falla ruidoso si no encuentra ninguno. Exporta `.env` y ejecuta `uvicorn backend.main:app --port 8003 --reload`.
- **`notifier/install.sh`:** genera y carga dos LaunchAgents en `~/Library/LaunchAgents/`:
  - `com.josemuniz.elearn-backend` — `RunAtLoad` + `KeepAlive`: backend siempre vivo (log: `~/Library/Logs/elearn-backend.log`).
  - `com.josemuniz.elearn-quiz` — `StartInterval` de N minutos (1–120, default 5): dispara el diálogo (log: `~/Library/Logs/elearn-quiz.log`).

---

## 3. Instalación

### 3.1 Requisitos

- macOS (el notificador usa `osascript` y `launchd`; la web funciona en cualquier OS)
- Python 3.10+ con pip
- Sin API keys: los tres servicios externos son gratuitos y anónimos

### 3.2 Instalación básica (solo web)

```bash
git clone <repo> english_learning && cd english_learning
pip install -r requirements.txt        # fastapi, uvicorn, httpx, python-dotenv
touch .env                             # start.sh lo exporta; puede estar vacío
./start.sh                             # → http://localhost:8003
```

Abrir `http://localhost:8003` en el navegador.

### 3.3 Instalación completa (quiz forzado nativo, macOS)

```bash
./notifier/install.sh 5      # diálogo de quiz cada 5 minutos (rango 1-120)
```

Esto instala y carga los dos LaunchAgents (backend KeepAlive + quiz periódico). El backend arranca solo al iniciar sesión y se reinicia si muere.

Cambiar el intervalo: volver a correr `./notifier/install.sh <minutos>` (recarga los agentes).

### 3.4 Desinstalación

```bash
./notifier/install.sh --uninstall    # descarga y borra ambos LaunchAgents
```

### 3.5 Dependencias de desarrollo

```bash
pip install -r requirements-dev.txt   # pytest
```

---

## 4. Cómo probar

### 4.1 Suite automatizada

```bash
python3 -m pytest backend/tests/ -v
```

Resultado esperado (verificado 2026-07-15): **47 passed** en <1 s.

| Archivo | Tests | Cubre |
|---|---|---|
| `backend/tests/test_quiz.py` | 23 | Motor de quiz: normalización/match, pesos, elegibilidad de tipos, distractores, construcción de preguntas |
| `backend/tests/test_words.py` | 11 | API de alta: palabra/frase EN, alta ES (palabra y frase invertida), dedup bidireccional (409), traducción fallida (400), `lang` inválido (422) y default |
| `backend/tests/test_notifier.py` | 13 | Notificador: construcción de diálogos, parsing de output de osascript, flujo "+ Agregar" con paso de idioma, cancelaciones, lock |

Los tests mockean las APIs externas: la suite corre offline y no toca `data/words.json` real.

### 4.2 Pruebas funcionales de la API (backend corriendo)

```bash
# Alta en inglés — card enriquecida completa
curl -s -X POST http://localhost:8003/api/words \
  -H 'Content-Type: application/json' -d '{"word": "whale"}' | python3 -m json.tool

# Alta en español — se traduce y enriquece igual (word_es conserva lo escrito)
curl -s -X POST http://localhost:8003/api/words \
  -H 'Content-Type: application/json' -d '{"word": "ballena", "lang": "es"}' | python3 -m json.tool

# Duplicado → 409 "Esa palabra ya está en tu vocabulario"
# (repetir cualquiera de los POST anteriores)

# lang inválido → 422 {"detail": "lang inválido (en|es)"}
curl -s -X POST http://localhost:8003/api/words \
  -H 'Content-Type: application/json' -d '{"word": "strong", "lang": "fr"}'

# Quiz: pregunta y respuesta
curl -s 'http://localhost:8003/api/quiz/next?types=typing&direction=es_to_en' | python3 -m json.tool
curl -s -X POST http://localhost:8003/api/quiz/answer \
  -H 'Content-Type: application/json' \
  -d '{"word_id": "<id>", "type": "typing", "direction": "es_to_en", "answer": "<respuesta>"}'

# Listado y borrado
curl -s http://localhost:8003/api/words | python3 -m json.tool
curl -s -X DELETE http://localhost:8003/api/words/<id>
```

### 4.3 Prueba de la web

1. Abrir `http://localhost:8003`.
2. Alta: elegir 🇪🇸 en el toggle, escribir `tiburón` → debe aparecer una card rica (`shark`, IPA, definición ES/EN, ejemplo traducido).
3. Duplicado: repetir el alta → toast de error "ya está en tu vocabulario".
4. Práctica: abrir la pestaña de práctica, responder un quiz de cada tipo; verificar que las estadísticas de la card cambian.
5. Timer: configurar el intervalo, esperar el disparo del modal.

### 4.4 Prueba del notificador nativo (macOS, interactiva)

```bash
# Disparo manual sin esperar a launchd:
/usr/bin/python3 notifier/quiz_dialog.py
```

1. Debe aparecer el diálogo de pregunta; responder → diálogo de resultado ✓/✗.
2. En el resultado, botón **"+ Agregar"** → diálogo de idioma (Español/Inglés) → escribir una palabra nueva → confirmación `word_en → word_es`. `Cancelar` en cualquier paso aborta sin llamar a la API.
3. Verificar el log: `tail ~/Library/Logs/elearn-quiz.log` (líneas `ok|wrong|skip|added`).
4. Con launchd instalado: esperar N minutos con el backend vivo; el diálogo debe aparecer solo. Anti-solape: si un diálogo queda abierto, la siguiente corrida se salta (`skip | lock activo`).

### 4.5 Troubleshooting

| Síntoma | Revisión |
|---|---|
| El diálogo no aparece | `launchctl list \| grep elearn` (ambos agentes cargados); `tail ~/Library/Logs/elearn-quiz.log` |
| Backend no responde | `tail ~/Library/Logs/elearn-backend.log`; `start.sh` falla ruidoso si no hay python3 con uvicorn+fastapi |
| Alta ES devuelve 400 | MyMemory no pudo traducir (o rate limit diario por IP) — reintentar o escribir la palabra en inglés |
| Alta devuelve 404 | La palabra no existe en dictionaryapi.dev — verificar ortografía |
