@echo off
title Jarvis OS Frontend
cd /d "%~dp0\frontend"
echo Installing frontend dependencies...
npm install
echo.
echo Starting frontend at http://localhost:5173
npm run dev
pause
