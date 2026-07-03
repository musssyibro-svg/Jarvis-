@echo off
REM ============================================================
REM  JARVIS — one-click start for Windows
REM  Double-click this file, or run it from the Node.js prompt.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ===========================================
echo   JARVIS - Starting up
echo ===========================================
echo.

REM --- 1. Check Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.11 and re-run.
  pause
  exit /b 1
)

REM --- 2. Check Ollama is running ---
echo [1/5] Checking Ollama...
curl -s http://127.0.0.1:11434/api/tags >nul 2>nul
if errorlevel 1 (
  echo       Ollama not responding. Starting it in a new window...
  start "Ollama" cmd /c "ollama serve"
  timeout /t 4 >nul
) else (
  echo       Ollama is running.
)

REM --- 3. Install backend dependencies ---
echo [2/5] Installing backend dependencies (first run only, may take a few minutes)...
cd backend
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo       Retrying with China mirror...
  python -m pip install -q -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple -r requirements.txt
)

REM --- 4. Start backend ---
echo [3/5] Starting backend on http://127.0.0.1:8000 ...
start "Jarvis Backend" cmd /k "python -m uvicorn main:app --reload --port 8000"
cd ..
timeout /t 5 >nul

REM --- 5. Start frontend ---
echo [4/5] Installing + starting frontend...
cd frontend
if not exist node_modules (
  echo       Installing frontend packages (first run only)...
  call npm install
)
echo [5/5] Launching UI...
start "Jarvis Frontend" cmd /k "npm run dev"
cd ..

echo.
echo ===========================================
echo   Jarvis is starting.
echo   Backend:  http://127.0.0.1:8000
echo   SSE test: http://127.0.0.1:8000/orchestrator/sse
echo   UI:       open the URL the frontend window prints
echo             (usually http://localhost:5173)
echo ===========================================
echo.
echo This window can be closed. The two new windows run Jarvis.
pause
