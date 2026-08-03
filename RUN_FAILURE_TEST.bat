@echo off
REM ============================================================
REM  JARVIS - Phase 0 failure injection (about 2 minutes)
REM
REM  Breaks Jarvis on purpose and checks it fails HONESTLY:
REM  notices the problem, names the real cause, doesn't retry
REM  things that can't work, and leaves nothing wedged.
REM
REM  Run this BEFORE any long soak test. A 24-hour run is a very
REM  slow way to discover a bug that shows up in 30 seconds.
REM ============================================================
title Jarvis - Failure Injection
cd /d "%~dp0"

REM Test each candidate by RUNNING it. "where py" succeeds whenever the
REM Python launcher is installed, even when it points at an interpreter
REM that has been uninstalled.
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY ( py -3 --version >nul 2>&1 && set "PY=py -3" )
if not defined PY ( python3 --version >nul 2>&1 && set "PY=python3" )
if not defined PY (
  echo  [X] Python not found on PATH.
  pause & exit /b 1
)

%PY% tools\failure_injection.py %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo  ================================================
  echo    Phase 0 passed. You can start the 4-hour soak.
  echo  ================================================
) else (
  echo  ================================================
  echo    Something failed. failure_injection_report.txt
  echo    has the details - send that file.
  echo  ================================================
)
echo.
pause
