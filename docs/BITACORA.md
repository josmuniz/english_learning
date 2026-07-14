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
