# Spec: Quiz Forzado Configurable — English Learning App

**Fecha:** 2026-07-14
**Estado:** Aprobado por el usuario (diseño validado en brainstorming)
**Alcance:** Fase 1 (in-app). Fase 2 (notificador nativo macOS) queda como gancho documentado, NO se implementa.

## 1. Problema

La app actual tiene práctica pasiva y opcional: el timer solo ofrece 15/20 min, el quiz es únicamente de tipeo con match exacto (frustrante en español por acentos y artículos), la configuración y el timer mueren al recargar la página, y la selección de palabras es 100% aleatoria aunque los contadores `times_practiced`/`times_correct` ya existen. El usuario quiere ser **interrumpido** cada N minutos (p. ej. 5) con preguntas aleatorias ES↔EN de opción múltiple para forzar el aprendizaje activo.

## 2. Objetivos

1. Intervalo configurable: presets 5/10/15/30 min + campo numérico libre (mín 1, máx 120).
2. Interrupción real: modal de quiz que se superpone a cualquier tab al vencer el timer.
3. Cuatro tipos de pregunta rotando aleatoriamente entre los habilitados.
4. Selección de palabras ponderada por fallos.
5. Configuración y estado del timer persistentes (sobreviven recarga de página).
6. Primeros tests automatizados del proyecto (pytest).

**No-objetivos:** mejorar la calidad de las traducciones del seed (mejora de datos separada) · implementar la fase 2 · autenticación/multiusuario · migrar el storage JSON.

## 3. Arquitectura (opción B aprobada)

Motor de quiz en el backend, stateless. El frontend solo pinta. La fase 2 consumirá los mismos endpoints.

```
frontend/index.html
  ├─ Config card (presets + campo libre + checkboxes tipos + nº preguntas/interrupción)
  │    └─ localStorage: { intervalMin, direction, types[], questionsPerInterrupt, timerActive, timerEndsAt }
  ├─ Timer (rearmado al recargar si timerActive)
  │    └─ al vencer → Modal Quiz (overlay, cualquier tab) + Notification si tab en background
  └─ Modal Quiz + Sesión de práctica (ambos consumen el mismo motor)
       │
       ▼
backend/main.py
  ├─ GET  /api/quiz/next?types=mc_word,mc_phrase,cloze,typing&direction=both
  │    1. selección ponderada por fallos
  │    2. tipo aleatorio entre habilitados (filtrado por elegibilidad de la palabra)
  │    3. distractores: 3 palabras distintas del propio vocabulario
  ├─ POST /api/quiz/answer  { word_id, type, direction, answer }
  │    valida (match tolerante) → actualiza stats → { correct, correct_answer, word }
  └─ data/words.json (sin cambios de esquema)
```

## 4. Contratos de API

### GET /api/quiz/next

Query params:
- `types`: CSV de `mc_word|mc_phrase|cloze|typing`. Default: los 4.
- `direction`: `es_to_en|en_to_es|both`. Default `both`.

Respuesta 200:
```json
{
  "word_id": "uuid",
  "type": "mc_word",
  "direction": "en_to_es",
  "prompt": "strong",
  "prompt_secondary": "(strɑng)",
  "options": ["fuerte", "feliz", "casa", "preciosa"],
  "hint": "adjective"
}
```
- `options` solo presente en `mc_word|mc_phrase|cloze` (4 opciones, orden aleatorio, la correcta incluida). En `typing` se omite.
- `cloze`: `prompt` = frase de ejemplo en inglés con la palabra reemplazada por `____` (reemplazo case-insensitive de la primera ocurrencia); `options` = 4 palabras en inglés. **Ignora `direction`** (es inherentemente EN).
- `mc_phrase`: respeta `direction` — `en_to_es`: `prompt` = `example_en`, `options` = 4 `example_es`; `es_to_en`: `prompt` = `example_es`, `options` = 4 `example_en`. Con `both`, la dirección se sortea por pregunta.
- La respuesta correcta NO viaja en el payload; se valida en `POST /api/quiz/answer` (stateless: el servidor la recomputa desde `words.json`).

Errores: `404` si el vocabulario está vacío. `422` si `types` no contiene ningún tipo válido.

### POST /api/quiz/answer

Body: `{ "word_id": str, "type": str, "direction": "es_to_en|en_to_es", "answer": str }`

Respuesta 200: `{ "correct": bool, "correct_answer": str, "word": {…} }` (mismo formato que el actual `/api/quiz/check`). Actualiza `times_practiced` y `times_correct`.

Errores: `404` palabra no encontrada.

**Compatibilidad:** `/api/quiz/check` se elimina y el frontend migra a `/api/quiz/answer` (app personal, sin otros consumidores).

## 5. Reglas de negocio

### 5.1 Selección ponderada por fallos
```
peso(w) = 3                                  si times_practiced == 0   (nueva: prioridad alta)
peso(w) = 1 + 4 * (1 - times_correct/times_practiced)   si times_practiced > 0
```
Selección por ruleta (random.choices con weights). Palabra dominada (100% aciertos) → peso 1; palabra que siempre falla → peso 5.

### 5.2 Elegibilidad por tipo
- `mc_word`, `typing`: cualquier palabra.
- `mc_phrase`: requiere `example_en` y `example_es` no vacíos (en la palabra y en los 3 distractores).
- `cloze`: requiere `example_en` que contenga `word_en` (case-insensitive).
- Si el tipo sorteado no es elegible para la palabra sorteada, se re-sortea el tipo entre los elegibles; si ninguno de los habilitados es elegible, fallback a `mc_word` (o `typing` si hay <4 palabras).

### 5.3 Degradación con vocabulario chico
- `< 4` palabras: los tipos de opción múltiple no son elegibles → todo cae a `typing`. El frontend muestra aviso "agrega al menos 4 palabras para opción múltiple".

### 5.4 Match tolerante (typing y validación MC)
Normalización de ambos lados antes de comparar:
1. `strip()`, lowercase
2. Quitar acentos/diacríticos (NFD → drop combining marks)
3. Quitar artículo inicial: `el|la|los|las|un|una|unos|unas|the|a|an` + espacio
4. Colapsar espacios múltiples

Acierto si coincide con la respuesta esperada o con el sinónimo (`synonym_en`/`synonym_es` según dirección). Para MC se compara la opción elegida con la respuesta correcta usando la misma normalización.

## 6. Frontend

### 6.1 Config card (reemplaza la actual de intervalo)
- Presets 5/10/15/30 + `<input type="number" min="1" max="120">`
- Checkboxes de los 4 tipos (default: todos)
- Selector de preguntas por interrupción: 1/3/5 (default 1)
- Dirección (ya existe): both/es_to_en/en_to_es
- Todo persiste en `localStorage` clave `elearn_config` al cambiar.

### 6.2 Timer persistente
- Al activar: guarda `timerEndsAt` (epoch ms) en localStorage.
- Al cargar la página: si `timerActive` y `timerEndsAt` futuro → rearma con el tiempo restante; si ya venció → dispara el quiz de inmediato.
- Al vencer: modal + `Notification` (ya existe el permiso flow) → rearma para el siguiente ciclo tras responder.

### 6.3 Modal de quiz
- Overlay `position:fixed` sobre cualquier tab; no cambia de vista.
- Pinta los 4 tipos: opciones como botones (MC/cloze), input (typing).
- Feedback inmediato correcto/incorrecto + respuesta correcta; botón "Siguiente" si quedan preguntas del bloque, "Cerrar" al terminar.
- Gancho fase 2: si la URL trae `?quiz=1` al cargar, abre el modal directamente.

### 6.4 Sesión de práctica existente
- `startPractice()`/`loadQuestion()` migran a consumir `GET /api/quiz/next` — se elimina la lógica duplicada de armado de pregunta del HTML. El paso "construye una frase" se mantiene sin cambios.

## 7. Tests (pytest — primeros del proyecto)

`backend/tests/test_quiz.py` con `TestClient` y fixture que apunta `DATA_FILE` a un JSON temporal (monkeypatch):
1. Ponderación: con stats forzadas, la palabra con más fallos sale significativamente más (muestra n=500, semilla fija).
2. `mc_word`: 4 opciones únicas, incluye la correcta, no viaja marcada.
3. `cloze`: el prompt contiene `____` y no contiene la palabra.
4. Elegibilidad: palabra sin ejemplo nunca genera `mc_phrase`/`cloze`.
5. Degradación: con 3 palabras, `types=mc_word` responde `typing`.
6. Match tolerante: `"El Fuerte "` ≡ `"fuerte"`, `"exquisite"` (sinónimo) acierta, acentos ignorados.
7. `POST /api/quiz/answer` actualiza `times_practiced`/`times_correct` en el archivo.
8. Vocabulario vacío → 404.

Correr: `python3 -m pytest backend/tests/ -v` (agregar `pytest` a requirements-dev o instalar suelto).

## 8. Fase 2 — Notificador nativo macOS (gancho, NO implementar)

- `launchd` plist (`~/Library/LaunchAgents/com.josemuniz.elearn-quiz.plist`) con `StartInterval` = N×60.
- Script: `curl GET /api/quiz/next` → si el backend responde, `osascript -e 'display notification …'` → al hacer click el usuario abre `http://localhost:8003/?quiz=1` (el modal se abre solo, §6.3).
- Requiere backend corriendo (launchd podría también levantar `start.sh` como KeepAlive — decisión de la fase 2).

## 9. Riesgos y bordes

| Riesgo | Mitigación |
|---|---|
| Distractores absurdos con vocabulario muy chico | Degradación §5.3 |
| `example_es` vacío en seed | Elegibilidad §5.2 excluye la palabra de mc_phrase |
| Doble disparo del timer con varias pestañas abiertas | Fuera de alcance (uso personal, 1 pestaña); documentado |
| Escritura concurrente de words.json | Ya existe hoy (sin lock); no empeora — fuera de alcance |
| Notification API denegada | El modal in-app funciona igual; la notificación es refuerzo |

## 10. Criterio de éxito

Con la pestaña abierta y timer en 5 min: cada 5 minutos aparece un modal con una pregunta aleatoria de los tipos habilitados; responder actualiza stats; las palabras falladas reaparecen más; recargar la página no pierde ni config ni timer; los 8 tests pasan.
