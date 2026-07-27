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

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
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
