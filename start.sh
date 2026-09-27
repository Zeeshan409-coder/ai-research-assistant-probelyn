#!/usr/bin/env bash
# One-command local start (macOS / Linux). Requires Python 3.11+, Node 18+ and Ollama.
set -e
cd "$(dirname "$0")"

if ! command -v ollama >/dev/null; then
  echo "Ollama not found. Install it from https://ollama.com/download and re-run." && exit 1
fi
ollama list >/dev/null 2>&1 || (ollama serve >/dev/null 2>&1 &) ; sleep 2
ollama list | grep -q "llama3.2" || ollama pull llama3.2
ollama list | grep -q "nomic-embed-text" || ollama pull nomic-embed-text

if [ ! -d frontend/dist ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

cd backend
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
echo "Probelyn running at http://localhost:8000"
uvicorn app.main:app --port 8000
