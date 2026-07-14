#!/bin/bash
cd "$(dirname "$0")"
export $(cat .env | xargs)
echo "🟢 English Learning App → http://localhost:8003"

# launchd runs with a minimal PATH that resolves "python3" to Apple's system
# interpreter, which lacks uvicorn/fastapi. Prefer whatever python3 is first
# on PATH (respects venvs), but fall back to the anaconda install that has
# the deps when the default interpreter can't import uvicorn.
PYTHON_BIN=""

# Try the system python3 first
if command -v python3 >/dev/null 2>&1; then
  if python3 -c "import uvicorn, fastapi" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  fi
fi

# If that didn't work, try the anaconda fallback (only if it exists)
if [ -z "$PYTHON_BIN" ]; then
  if [ -f "/opt/anaconda3/bin/python3" ] && /opt/anaconda3/bin/python3 -c "import uvicorn, fastapi" >/dev/null 2>&1; then
    PYTHON_BIN="/opt/anaconda3/bin/python3"
  fi
fi

# If we still don't have a python, fail loud
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: no python3 with uvicorn+fastapi found" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m uvicorn backend.main:app --port 8003 --reload
