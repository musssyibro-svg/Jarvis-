#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo ""
echo " JARVIS v3 — Autonomous Income AI"
echo " ============================================================"

# Ollama
if ! lsof -i:11434 -sTCP:LISTEN &>/dev/null 2>&1; then
    echo "[1/3] Starting Ollama..."
    ollama serve &
    sleep 3
else
    echo "[1/3] Ollama already running."
fi

# Backend
echo "[2/3] Starting FastAPI backend..."
cd "$DIR/backend"
uvicorn main:app --reload --port 8000 &
sleep 3

# Frontend
echo "[3/3] Starting React frontend..."
cd "$DIR/frontend"
npm run dev &

echo ""
echo " Open: http://localhost:5173"
echo " Press Ctrl+C to stop all."
wait
