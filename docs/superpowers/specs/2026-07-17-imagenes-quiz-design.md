# Spec: Imagen/escena por palabra con validación, y uso en el quiz

**Fecha:** 2026-07-17
**Estado:** Aprobado (IA generada + validación del usuario + ambos usos en quiz)

## Problema

El vocabulario es solo texto. El usuario quiere una imagen/escena por palabra o frase que
ilustre su significado, **validada por él** (debe entender la imagen), y que el quiz la use:
como pregunta visual (ver la escena → decir la palabra) y como apoyo en los tipos existentes.

## Alcance

1. Generación de escena con IA (Gemini) por palabra/frase, al agregar y a demanda.
2. **Validación del usuario**: la imagen queda `pending` hasta que el usuario la apruebe;
   solo las aprobadas se usan en el quiz.
3. Nuevo tipo de pregunta `mc_image` (escena → elegir la palabra entre 4).
4. Apoyo visual: los tipos existentes muestran la escena aprobada si existe (solo web).
5. Grilla: miniatura + estado + acciones (aprobar / regenerar / descartar).
6. **Límite**: el popup nativo AppleScript no muestra imágenes → `mc_image` y el apoyo
   visual son solo web; el notifier no pide `mc_image`.

## Diseño

### 1. Datos y storage

- Campos nuevos por entrada en `words.json`:
  - `image`: ruta relativa `"images/<word_id>.png"` o `""`.
  - `image_status`: `"none" | "pending" | "approved"` (default `"none"`; entradas legacy
    sin el campo = `"none"`).
- Archivos en `data/images/` (crear dir si falta; se versiona en git como los datos).
- Servidos con `app.mount("/images", StaticFiles(directory=data/images))`.

### 2. Generación (backend)

- Cliente Gemini en `backend/imagen.py` (módulo nuevo): función
  `generate_scene(word: dict) -> bytes` — REST a la API de Gemini
  (`gemini-2.5-flash-image`, respuesta inline base64 → bytes PNG) con `httpx`.
  Prompt: escena simple y clara que ilustre `word_en` usando `example_en` como contexto,
  sin texto dentro de la imagen (para no regalar la respuesta), estilo ilustración limpia.
- API key: `GEMINI_API_KEY` del entorno. `notifier/install.sh` la inyecta como
  `EnvironmentVariables` en el plist del backend (tomándola del entorno del instalador,
  con aviso si falta). Sin key → los endpoints de imagen responden 503
  `"Generación de imágenes no configurada (GEMINI_API_KEY)"`; el alta de palabras NO falla.
- **Al agregar una palabra** (`POST /api/words`): la entrada se crea y responde igual que
  hoy; la generación corre en background (`asyncio.create_task`) y al terminar guarda el
  PNG y setea `image` + `image_status: "pending"`. Errores de generación → log, entrada
  queda `"none"` (reintentable a demanda).
- `POST /api/words/{id}/image` → (re)genera a demanda (sobrescribe el PNG, estado vuelve a
  `pending`). Responde la entrada actualizada. 404 si el id no existe, 503 sin key.
- `PUT /api/words/{id}/image/status` body `{"status": "approved"}` (o `"none"` para
  descartar: borra el archivo y limpia campos). Estados inválidos → 422.

### 3. Quiz

- `backend/quiz.py`:
  - `ALL_TYPES` + `"mc_image"`.
  - Elegibilidad `mc_image`: la palabra tiene `image_status == "approved"` y hay ≥4
    entradas en el vocabulario (mismos distractores de texto que `mc_word`).
  - Payload de `mc_image`: como `mc_word` es_to_en pero `prompt` = "¿Qué palabra es?" y
    campo `image_url` (la escena es el enunciado). Sin dirección inversa.
  - Todos los tipos: si la palabra del quiz tiene imagen aprobada, el payload incluye
    `image_url` (apoyo visual); el frontend decide mostrarla (en `mc_image` es el
    enunciado; en el resto, apoyo).
- `notifier/quiz_dialog.py`: pide `/api/quiz/next` con `types` explícitos SIN `mc_image`
  (AppleScript no muestra imágenes) e ignora `image_url`.

### 4. Web (`frontend/index.html`)

- **Grilla**: columna nueva 🖼 (tras el checkbox): miniatura 40px clickeable si hay imagen
  (badge "pendiente" amarillo si `pending`), botón 🎨 para generar/regenerar.
- **Modal/lightbox** al click: imagen grande + botones según estado:
  `pending` → "✓ La entiendo (aprobar)" / "🎨 Regenerar" / "✕ Descartar";
  `approved` → "🎨 Regenerar" / "✕ Descartar".
- **Práctica web**: renderiza `mc_image` (imagen como enunciado + 4 opciones) y muestra
  `image_url` como apoyo en los demás tipos (imagen pequeña sobre la pregunta).
- Botón "🎨 Generar faltantes" en la sección de vocabulario: recorre las entradas sin
  imagen una a una (secuencial, con progreso y opción de parar).

### 5. Tests (pytest; Gemini SIEMPRE mockeado)

- `generate_scene` no se llama en tests de alta (task en background monkeypatcheada).
- `POST /{id}/image`: guarda archivo, setea `pending`; 404; 503 sin key.
- `PUT /{id}/image/status`: `approved` ok; `none` borra archivo; 422 inválido.
- Elegibilidad `mc_image`: solo con imagen aprobada y ≥4 palabras; `pending` NO elegible.
- Payload: `image_url` presente en tipos de texto cuando hay imagen aprobada; ausente si no.
- Notifier: la URL de `/api/quiz/next` que arma no incluye `mc_image`.

### 6. Verificación funcional

- Suite completa en verde.
- Flujo real en browser: generar imagen de una palabra (Gemini real, 1-2 imágenes),
  aprobarla desde el lightbox, verla como apoyo en práctica, y responder un `mc_image`.
- Popup nativo sigue funcionando sin cambios visibles.

## Fuera de alcance

- Feature A panel de control (spec aparte, esperando review) y Feature B motor adaptativo.
- Subir imágenes propias (posible extensión futura).
- Imágenes en el diálogo nativo (limitación de AppleScript).
