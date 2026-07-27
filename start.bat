@echo off
title Jarvis OS V8
echo ============================================================
echo   JARVIS OS V8 - AUTONOMOUS DESKTOP + FREELANCE AGENT
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/5] Installing Python dependencies...
pip install -r backend\requirements.txt -q --break-system-packages 2>nul || pip install -r backend\requirements.txt -q

echo [2/5] Installing Playwright browsers (Edge + Chromium)...
python -m playwright install msedge --quiet 2>nul
python -m playwright install chromium --quiet 2>nul

echo [3/5] Creating browser profile directory...
if not exist "backend\edge-profile" mkdir backend\edge-profile

echo [4/5] Pulling Ollama models (if not already pulled)...
echo   Fast model:      ollama pull qwen2.5:0.5b
echo   Reasoning model: ollama pull deepseek-r1:1.5b
echo   Vision model:    ollama pull llava:7b  (optional, ~4GB)
echo   (Pull manually in a separate terminal if not done yet)
echo.

echo [5/5] Starting Jarvis OS V8 backend...
echo.
echo   Backend API: http://127.0.0.1:8000
echo   API Docs:    http://127.0.0.1:8000/docs
echo.
echo   To start frontend: run start_frontend.bat in another window
echo.

cd backend
python -m uvicorn main:app --reload --port 8000 --host 127.0.0.1
pause
