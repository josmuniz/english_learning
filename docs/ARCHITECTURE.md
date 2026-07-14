# English Learning App — Arquitectura

## Visión

App local de vocabulario inglés→español. Una sola página HTML consume una API FastAPI que agrega tres servicios públicos gratuitos y persiste en un archivo JSON.

## Componentes

| Componente | Tecnología | Ubicación | Puerto |
|---|---|---|---|
| Frontend | HTML/CSS/JS vanilla single-file | `frontend/index.html` | servido por el backend |
| Backend | FastAPI + Uvicorn | `backend/main.py` | 8003 |
| Storage | JSON plano | `data/words.json` | — |
| Motor de quiz | Python puro (sin I/O) | `backend/quiz.py` | — |
| Notificador nativo | Python stdlib + osascript + launchd | `notifier/quiz_dialog.py` + `notifier/install.sh` | — |

## Flujo de datos

```
Usuario escribe palabra
  → POST backend
      → dictionaryapi.dev  (definición, IPA, ejemplos)
      → mymemory.translated.net (traducción EN→ES)
      → datamuse.com (palabras relacionadas)
      → ipa_to_spanish() convierte IPA a fonética española
  → merge → append a data/words.json → respuesta al frontend
```

```
Timer (frontend, persistente en localStorage)
  → GET /api/quiz/next (ponderado por fallos, 4 tipos, distractores del propio vocabulario)
  → modal responde → POST /api/quiz/answer (match tolerante) → stats en words.json
```

```
launchd (com.josemuniz.elearn-quiz, cada N min)
  → notifier/quiz_dialog.py → GET /api/quiz/next
  → diálogo AppleScript (choose from list / display dialog) — el quiz se responde ahí
  → POST /api/quiz/answer → resultado ✓/✗ con "+ Agregar" (POST /api/words)
launchd (com.josemuniz.elearn-backend, KeepAlive) mantiene el backend :8003 siempre vivo
```
Recomendación: con el notificador instalado, dejar el timer web desactivado (§6 del spec fase 2).

## Decisiones

- **Sin DB:** volumen personal pequeño; `words.json` completo se relee/reescribe por operación.
- **Fonética española propia:** mapa IPA→grafemas españoles (`_IPA_MAP`), dígrafos procesados antes que símbolos simples porque el orden de reemplazo importa.
- **APIs gratuitas sin key:** dictionaryapi.dev, MyMemory y Datamuse no requieren autenticación (MyMemory tiene rate limit diario por IP).

## Arranque

```bash
./start.sh   # exporta .env y levanta uvicorn :8003 con --reload
```
