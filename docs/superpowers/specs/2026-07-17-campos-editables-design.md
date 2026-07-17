# Spec: Campos editables por entrada + ejemplos cortos

**Fecha:** 2026-07-17
**Estado:** Aprobado por el usuario (diseño validado en sesión)

## Problema

Las frases (`type: "phrase"`) se guardan siempre con `ipa` y `pronunciation_es` vacíos: el
pipeline solo obtiene pronunciación de la API de diccionario, que no cubre frases
(`_add_phrase`, `backend/main.py`). No existe forma de completar o corregir esos campos después
del alta. Además, los ejemplos que devuelve el diccionario pueden ser largos, y el usuario los
quiere cortos (≤10 palabras).

## Alcance

1. **Vista de grilla** (tipo planilla Excel) que reemplaza la lista de tarjetas: una fila por
   entrada, columnas hacia la derecha para aprovechar la pantalla.
2. **Edición inline por fila** de campos de cualquier entrada (palabra o frase).
3. Campos editables: `pronunciation_es`, `ipa`, `synonym_en`, `synonym_es`, `antonym_en`,
   `antonym_es`, `example_en`, `example_es`. En **frases** solo `pronunciation_es` e `ipa`
   (sinónimo/antónimo/ejemplo no aplican a frases y no se muestran ni se editan).
4. Campos NO editables (protegidos): `id`, `created_at`, `word_en`, `word_es`, `type`,
   `definition_en`, `definition_es`, `times_practiced`, `times_correct`.
5. **Ejemplos cortos al generar:** el pipeline elige ejemplos de ≤10 palabras.
6. Sin cambios en el quiz ni en el notifier (leen los mismos campos de `words.json`).

## Diseño

### 1. Backend — `PATCH /api/words/{word_id}`

- Modelo Pydantic `WordUpdateRequest`: los 8 campos editables, todos opcionales (`None` = no tocar).
- Solo se actualizan los campos presentes en el request (lista blanca explícita).
- Strings se guardan con `strip()`.
- Validación: si `example_en` o `example_es` tiene más de 10 palabras → `422` con mensaje
  `"El ejemplo no puede superar 10 palabras"`.
- `404` si `word_id` no existe.
- Respuesta: la entrada completa actualizada.
- El endpoint es genérico por tipo: la restricción "frases sin sinónimo/antónimo/ejemplo" se
  aplica en la UI (no ofrece esos inputs), no en el backend.

### 2. Pipeline — selector de ejemplos cortos

En `fetch_dictionary()` (`backend/main.py`):

- Al recorrer `all_meanings`, recolectar candidatos a ejemplo y **preferir el primero con
  ≤10 palabras**.
- Si ningún candidato cumple, recortar el primer ejemplo encontrado a sus primeras 10 palabras.
- Los ejemplos de fallback sintéticos ya cumplen (≤6 palabras).
- `example_es` hereda el ejemplo corto porque se traduce después.

### 3. Frontend — grilla con edición inline por fila (`renderWords()`, `frontend/index.html`)

Layout de tabla (reemplaza las tarjetas), columnas en este orden:

```
| Inglés | Sonido | Español | Sinónimo | Antónimo | Ejemplo | ✏️ 🗑 |
```

- **Inglés** = `word_en`; **Sonido** = `pronunciation_es` (con IPA como tooltip/subtexto si
  existe); **Español** = `word_es`; **Sinónimo/Antónimo** = par EN (ES como subtexto);
  **Ejemplo** = `example_en` (ES como subtexto).
- **Frases** (`type: "phrase"`): las celdas Sinónimo/Antónimo/Ejemplo van vacías (—) y no son
  editables.
- Filas compactas, tabla con scroll horizontal propio si no cabe (la página no scrollea
  lateral).
- Botón ✏️ por fila. Estado `editingId` (una fila en edición a la vez); ✏️ en otra fila mueve
  el foco; Cancelar limpia. En edición, las celdas editables se vuelven inputs prefilled
  (para palabras: sonido, IPA, sinónimo EN/ES, antónimo EN/ES, ejemplo EN/ES; para frases:
  solo sonido e IPA) + Guardar/Cancelar en la columna de acciones. Los campos vacíos (caso
  típico: frase sin pronunciación) aparecen como inputs vacíos listos para completar.
- Guardar → `PATCH /api/words/{id}` → actualizar el objeto en la lista local → re-render.
- Error del backend (ej. >10 palabras) → mostrar el mensaje en la fila sin perder lo tecleado.
- **Hardening incluido:** aplicar `esc()` a todos los campos interpolados en `renderWords()`
  (cierra el follow-up XSS pendiente de fase 1).

### 4. Tests (pytest, `backend/tests/`)

- PATCH actualiza cada campo editable y persiste en `words.json`.
- PATCH ignora campos protegidos si vienen en el body (o los rechaza — comportamiento: se
  ignoran silenciosamente al no estar en el modelo).
- PATCH parcial: solo cambia lo enviado.
- `404` con id inexistente.
- `422` con ejemplo de 11+ palabras (EN y ES).
- Selector de ejemplos: con diccionario mockeado que trae un ejemplo largo primero y uno corto
  después → elige el corto; con solo ejemplos largos → recorta a 10 palabras.

### 5. Verificación funcional

- Suite completa pytest (47 existentes + nuevos) en verde.
- Flujo real en browser: la grilla renderiza con las columnas en orden (frases sin
  sinónimo/antónimo/ejemplo), editar pronunciación de una frase sin pronunciación, guardar,
  recargar y confirmar persistencia.
