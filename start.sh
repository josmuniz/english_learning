#!/bin/bash
cd "$(dirname "$0")"
export $(cat .env | xargs)
echo "🟢 English Learning App → http://localhost:8003"

# launchd runs with a minimal PATH that resolves "python3" to Apple's system
# interpreter, which lacks uvicorn/fastapi. Prefer whatever python3 is first
# on PATH (respects venvs), but fall back to the anaconda install that has
# the deps when the default interpreter can't import uvicorn.
PYTHON_BIN="$(command -v python3)"
"$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1 || PYTHON_BIN="/opt/anaconda3/bin/python3"

exec "$PYTHON_BIN" -m uvicorn backend.main:app --port 8003 --reload
