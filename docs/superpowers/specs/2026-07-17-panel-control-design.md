# Spec: Panel de control web para el diálogo de quiz

**Fecha:** 2026-07-17
**Estado:** Aprobado (Enfoque 1, config-driven)

## Problema

El popup nativo de quiz (launchd → `notifier/quiz_dialog.py`) no tiene ningún control en
runtime: el intervalo queda horneado en el plist al instalar (default 5 min), no se puede
pausar sin `launchctl` en terminal, no se puede disparar a demanda, y no se pueden elegir
tipos de pregunta ni dirección. El usuario quiere controlar todas las interfaces desde la
página web.

## Alcance

1. **Config compartida** `data/settings.json` — única fuente de verdad para web y diálogo.
2. **Endpoints**: `GET /api/settings`, `PUT /api/settings`, `POST /api/quiz/trigger`.
3. **Notifier config-driven**: launchd dispara cada 1 min; el diálogo decide si mostrarse
   (pausa + cadencia) y usa tipos/dirección configurados.
4. **Web**: sección Ajustes con pausar/reanudar, frecuencia, tipos, dirección y
   "Pregúntame ahora".
5. El quiz web usa los mismos tipos/dirección configurados.

**Fuera de alcance** (Feature B, spec futuro): motor adaptativo de preguntas — prioridad a
falladas, cadencia menor a acertadas, escalada de método (seleccionar → escribir →
pronunciar), responder todas.

## Diseño

### 1. Config — `data/settings.json`

```json
{
  "quiz_paused": false,
  "interval_minutes": 5,
  "types": ["mc_word", "mc_phrase", "cloze", "typing"],
  "direction": "both"
}
```

- Helpers `load_settings()` / `save_settings()` en `backend/main.py`, con defaults si el
  archivo no existe o le faltan claves (merge de defaults).
- `direction`: `"both" | "es_to_en" | "en_to_es"`.

### 2. Backend — endpoints

- `GET /api/settings` → settings completos (con defaults aplicados).
- `PUT /api/settings` — body parcial (modelo Pydantic, campos opcionales):
  - `interval_minutes`: entero 1–120 → fuera de rango 422 `"Frecuencia inválida (1–120 min)"`.
  - `types`: lista no vacía, subconjunto de los 4 tipos → inválido 422 `"Tipos inválidos"`.
  - `direction`: enum → inválido 422 `"Dirección inválida"`.
  - `quiz_paused`: bool.
  - Responde settings completos actualizados.
- `POST /api/quiz/trigger` → lanza `notifier/quiz_dialog.py --now` con `subprocess.Popen`
  (fire-and-forget, no bloquea la respuesta); responde `{"ok": true}`. Si el script no
  existe → 500 con detail claro.

### 3. Notifier — `notifier/quiz_dialog.py`

- Al inicio (tras el lock): `GET /api/settings`.
  - `quiz_paused` → log y exit 0.
  - Cadencia: lee `data/.quiz_last_shown` (timestamp epoch). Si
    `now - last_shown < interval_minutes*60` → exit 0. Al mostrar un quiz, escribe el
    timestamp.
  - Si la API no responde, comportamiento actual (mejor esfuerzo, no crashear).
- `--now` (nuevo flag): salta pausa y cadencia (pero respeta el lock anti-doble-diálogo).
- `/api/quiz/next` se llama con `types` y dirección de settings (`both` → no filtrar).
- `notifier/install.sh`: el intervalo del plist del quiz pasa a fijo 60 s (el argumento
  `MINUTES` ahora setea `interval_minutes` inicial en settings, no el plist).

### 4. Web — sección Ajustes (`frontend/index.html`)

- Card "Ajustes del quiz" dentro de la sección de práctica existente (misma página, sin tab
  nuevo):
  - Toggle **Quiz automático** (pausar/reanudar) con estado visible.
  - **Frecuencia**: presets 1/5/15/30/60 min + input custom (1–120).
  - **Tipos de pregunta**: 4 checkboxes (mínimo 1).
  - **Dirección**: both / ES→EN / EN→ES.
  - Botón **"🔔 Pregúntame ahora"** → `POST /api/quiz/trigger`.
- Cambios se guardan con `PUT /api/settings` al modificar (sin botón guardar global);
  feedback con `toast()`. Errores 422 → toast de error.
- El quiz web (sesión de práctica) usa `types`/`direction` de settings al pedir
  `/api/quiz/next`.

### 5. Tests (pytest)

- Settings: GET con defaults (sin archivo), PUT parcial (merge), validaciones 422
  (intervalo 0/121, types vacío o desconocido, direction inválida), persistencia.
- Trigger: `POST /api/quiz/trigger` con `subprocess.Popen` monkeypatcheado → invocado con
  `--now`; script inexistente → 500.
- Notifier (tests de funciones puras/monkeypatch, patrón de `test_notifier.py`):
  pausado → no muestra; no vencido → no muestra; vencido → muestra y actualiza timestamp;
  `--now` ignora cadencia; types/direction llegan a la URL de `/api/quiz/next`.

### 6. Verificación funcional

- Suite completa en verde.
- Web real: cambiar frecuencia y pausa desde Ajustes → `settings.json` refleja; botón
  "Pregúntame ahora" abre el diálogo nativo (validación interactiva del usuario si la
  sesión no tiene GUI).
- Redeploy launchd (`notifier/install.sh`) para el plist de 60 s.
