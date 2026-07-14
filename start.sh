#!/bin/bash
cd "$(dirname "$0")"
export $(cat .env | xargs)
echo "🟢 English Learning App → http://localhost:8003"
python3 -m uvicorn backend.main:app --port 8003 --reload
