# Spec: Diálogos — marcado de frases y quiz "siguiente frase"

**Fecha:** 2026-07-18
**Estado:** Aprobado (requisito del usuario: marcar frases de un diálogo; el quiz
selecciona la frase N y la respuesta correcta es la frase N+1).

## Problema

Hay frases sueltas y frases que pertenecen a un diálogo. Hoy no hay forma de marcar la
pertenencia ni de practicar la continuidad del diálogo.

## Alcance

1. **Marcado**: cada frase puede llevar `dialogue` (nombre, "" = suelta) y `dialogue_pos`
   (número de línea, entero ≥ 1). Se editan en la fila (solo frases). La grilla muestra
   badge `💬 nombre #pos`.
2. **Quiz — tipo `dialogue_next`**: si un diálogo tiene 2+ líneas, el sistema puede
   mostrar la línea N (en inglés) y la respuesta correcta es la línea N+1 (siguiente en
   orden de `dialogue_pos`; la última línea no se pregunta). Opción múltiple con 4
   opciones. Funciona en la práctica web Y en el popup nativo (es solo texto).
3. Sin cambios de esquema para palabras sueltas (campos ausentes = sin diálogo).

## Diseño

### Datos
- `dialogue: str` (default `""`), `dialogue_pos: int` (default `0` = sin posición).
  Marcado completo = nombre no vacío y pos ≥ 1; marcado incompleto simplemente no es
  elegible para el quiz (sin error).

### Backend — PATCH
- `WordUpdateRequest` += `dialogue: str | None`, `dialogue_pos: int | None`.
- Validación: `dialogue_pos` < 1 (cuando se envía y `dialogue` queda no vacío) → 422
  `"La línea del diálogo debe ser 1 o mayor"`. Si `dialogue` se deja vacío se limpia
  también `dialogue_pos` (a 0).
- La restricción "solo frases llevan diálogo" es de UI (el endpoint queda genérico,
  como quiz_enabled).

### Motor de quiz (`backend/quiz.py`)
- `ALL_TYPES` += `"dialogue_next"`.
- `dialogue_lines(name, all_words)`: frases con ese `dialogue` y `dialogue_pos` ≥ 1,
  ordenadas por pos (ante pos duplicada, la primera encontrada).
- `next_line(word, all_words)`: la línea con menor pos estrictamente mayor que la del
  word (tolera huecos: 2,4 → siguiente de 2 es 4), o `None`.
- Elegibilidad `dialogue_next`: `len(all_words) >= 4`, el word tiene diálogo completo y
  `next_line` no es None.
- `build_question`: dirección forzada `es_to_en` (la respuesta es inglés). `prompt` =
  línea N (`word_en`). Opciones: `next.word_en` + 3 distractores — primero otras líneas
  del mismo diálogo (≠N, ≠N+1), luego otras frases, luego cualquier otra palabra.
- `expected_answer(word, qtype, direction, all_words=None)`: para `dialogue_next`
  devuelve `(next_line.word_en, "")`. `main.quiz_answer` pasa `all_words`.
- El default del parámetro `types` de `GET /api/quiz/next` **incluye** `dialogue_next`
  (a diferencia de `mc_image`): el popup lo recibe.

### Notifier
- `PROMPT_LABEL[("dialogue_next", "es_to_en")] = "¿Cuál es la siguiente frase del diálogo?"`.
  El render de opciones ya es genérico (choose from list).

### Web
- Fila de edición (frases): inputs `Diálogo` y `# línea` (junto a sonido/traducción);
  validación cliente: pos no numérica → error en fila sin perder lo tecleado.
- `renderRow`: badge `💬 nombre #pos` como subtexto en la celda Inglés (solo marcadas).
- `PROMPT_LABEL.dialogue_next`, `DEFAULT_CFG.types` += `dialogue_next` + checkbox de tipo.

### Tests
- PATCH: asignar diálogo+pos; 422 pos 0; limpiar diálogo limpia pos.
- Motor: orden con huecos; última línea no elegible; diálogo de 1 línea no elegible;
  payload (prompt = N, correcta = N+1, 4 opciones); distractores sin N+1 duplicada;
  expected_answer con all_words; default de types incluye dialogue_next.
- Notifier: label del tipo nuevo.
- Browser: marcar 2 frases como diálogo desde la UI, práctica con solo dialogue_next,
  responder correcta e incorrecta.
