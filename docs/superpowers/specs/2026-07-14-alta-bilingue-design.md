# Spec: Alta bilingüe — agregar palabras/frases en español o inglés

**Fecha:** 2026-07-14
**Estado:** Aprobado por el usuario (diseño validado en brainstorming)
**Depende de:** Fase 1 (`1c66cee`) y Fase 2 (`41b1022`) mergeadas — pipeline de palabras, camino frase, diálogo nativo "+ Agregar".

## 1. Problema

`POST /api/words` asume entrada en inglés: busca en dictionaryapi.dev (EN) y traduce EN→ES. Si el usuario escribe "mariposa" falla el lookup; si escribe una frase en español, se guarda invertida (la frase española como `word_en`). El usuario quiere escribir en cualquiera de los dos idiomas, desde la web y desde el diálogo nativo.

Decisión de brainstorming: **selector manual EN/ES** (las palabras ambiguas — "actual", "hospital" — hacen poco fiable la autodetección) y **enfoque A**: la entrada en español se traduce y luego se enriquece con el pipeline inglés completo, para que la card quede igual de rica.

## 2. Objetivos

1. `POST /api/words` acepta `lang: "en" | "es"` (default `"en"` — retrocompatible).
2. Entrada ES (palabra): traducir ES→EN → pipeline inglés completo sobre la traducción → `word_es` = entrada original del usuario.
3. Entrada ES (frase, contiene espacio): `word_en` = traducción, `word_es` = entrada, `type: "phrase"` (camino frase invertido).
4. Web: toggle 🇬🇧/🇪🇸 junto al input (default Inglés, persistido en `localStorage` dentro de `elearn_config` como `addLang`), placeholder según idioma.
5. Diálogo nativo "+ Agregar": paso previo de idioma con botones `{Cancelar, Español, Inglés}`.
6. Dedup mejorado: contra `word_en` **y** `word_es`, case-insensitive, en ambos idiomas de entrada.

**No-objetivos:** autodetección de idioma · otros idiomas · editar el idioma de entradas existentes · cambios al motor de quiz o al esquema de words.json.

## 3. Backend (`backend/main.py`)

### 3.1 Modelo

```python
class WordRequest(BaseModel):
    word: str
    lang: str = "en"   # "en" | "es"
```

`lang` fuera de `("en", "es")` → 422 (validación explícita en el endpoint, coherente con quiz_next/quiz_answer).

### 3.2 Flujo de `add_word`

```
entrada = strip().lower()  (validaciones actuales: vacío 400, >80 chars 400)
dedup: si entrada == word_en.lower() O entrada == word_es.lower() de algún registro → 409
lang == "es":
    traducción = translate(entrada, src="es", tgt="en")   ← translate() ya soporta src/tgt
    si traducción vacía → 400 "No se pudo traducir; intenta escribirla en inglés"
    traducción = traducción.strip().lower()
    re-chequear dedup con la traducción (contra word_en) → 409 si ya existe
    si entrada tiene espacio → camino frase con word_en=traducción, word_es=entrada
    si no → pipeline inglés completo sobre `traducción`, y al final word_es = entrada original
            (NO la re-traducción EN→ES del pipeline)
lang == "en": comportamiento actual sin cambios (palabra → pipeline, frase → _add_phrase)
```

Nota: si la traducción de una palabra ES resulta multi-palabra (p. ej. "madrugar" → "get up early"), se trata como frase (camino frase con `word_en` = traducción multi-palabra). Regla general: **el camino se decide por la forma de `word_en` final**.

### 3.3 `_add_phrase` generalizado

Firma pasa a `_add_phrase(word_en: str, word_es: str, words: list)` — el llamador decide qué va en cada campo (EN: `word_es` = traducción o fallback; ES: `word_es` = entrada). El fallback `word_es or word_en` se mantiene para el camino EN.

## 4. Web (`frontend/index.html`)

- Junto al input de agregar: dos botones toggle `🇬🇧 Inglés` / `🇪🇸 Español` (mismo patrón visual que los presets del timer). Estado en `cfg.addLang` (`"en"` default), persistido con el `saveConfig()` existente y restaurado en `applyConfigToUI()`.
- Placeholder según idioma: EN → `"Ej: perseverance, break the ice…"` · ES → `"Ej: mariposa, romper el hielo…"`.
- `addWord()` envía `{word, lang: cfg.addLang}`.

## 5. Diálogo nativo (`notifier/quiz_dialog.py`)

- `build_add_lang_dialog() -> str`: `display dialog "¿En qué idioma vas a escribir?" buttons {"Cancelar", "Español", "Inglés"} default button "Inglés" with title "English Learning" giving up after 60`.
- `offer_add_word()`: primero el diálogo de idioma (Cancelar/timeout → abortar sin POST); luego el diálogo de texto actual; el POST incluye `"lang": "es"|"en"` según el botón.
- El diálogo de confirmación muestra `word_en → word_es` igual que hoy.

## 6. Tests (~7 nuevos, suite 40 → ~47)

Backend (`test_words.py`, con mocks existentes):
1. `lang: "es"` palabra → `word_es` = entrada original, `word_en` = traducción, pipeline EN invocado (fake_dictionary llamado con la traducción).
2. `lang: "es"` frase → `type: "phrase"`, campos invertidos correctamente.
3. `lang: "es"` con translate vacío → 400.
4. Dedup por `word_es`: existiendo un registro con `word_es: "fuerte"`, POST `{"word": "Fuerte", "lang": "es"}` → 409.
5. `lang` inválido → 422. Default sin `lang` → camino EN (retrocompatible).

Notificador (`test_notifier.py`):
6. `build_add_lang_dialog` contiene los 3 botones.
7. Flujo "+ Agregar" con idioma: mock devuelve `button returned:Español` → el POST a `/api/words` lleva `"lang": "es"`; `Cancelar` → sin POST.

## 7. Criterio de éxito

1. Web con 🇪🇸: agregar "mariposa" crea card rica (definición/IPA/ejemplo de "butterfly") con `word_es: "mariposa"`; agregar "romper el hielo" crea frase con `word_en` en inglés.
2. Web con 🇬🇧: comportamiento idéntico al actual.
3. Diálogo nativo: "+ Agregar" → elegir Español → escribir "tiburón" → confirma `shark → tiburón`.
4. Duplicados bloqueados en ambos sentidos (agregar "strong" y luego "fuerte" → 409).
5. Suite pytest completa verde (~47).

## 8. Riesgos y bordes

| Riesgo | Mitigación |
|---|---|
| Traducción ES→EN incorrecta (MyMemory) | La card muestra `word_en → word_es`; el usuario ve el error de inmediato y puede borrar. Aceptado (mismo riesgo que EN→ES actual) |
| Palabra ES cuya traducción EN no está en dictionaryapi | El pipeline EN ya lanza 404 con mensaje; el registro no se crea a medias |
| Traducción multi-palabra de una palabra ES | Regla §3.2: decide la forma de `word_en` final → camino frase |
| MyMemory rate limit | Mismo comportamiento actual; el 400 de "no se pudo traducir" lo comunica |
