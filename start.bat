@echo off
REM One-command local start for Windows. Requires Python 3.11+, Node 18+ and Ollama.
cd /d "%~dp0"

where ollama >nul 2>nul || (echo Ollama not found. Install it from https://ollama.com/download & pause & exit /b 1)
ollama list | findstr /C:"llama3.2" >nul || ollama pull llama3.2
ollama list | findstr /C:"nomic-embed-text" >nul || ollama pull nomic-embed-text

if not exist frontend\dist (
  pushd frontend
  call npm install --no-audit --no-fund
  call npm run build
  popd
)

cd backend
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo Probelyn running at http://localhost:8000
start "" http://localhost:8000
uvicorn app.main:app --port 8000
