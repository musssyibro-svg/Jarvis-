@echo off
REM ============================================================
REM  JARVIS DOCTOR - run this FIRST when something will not start.
REM  Checks every dependency and the mistakes that produce
REM  misleading errors, then prints exactly what to fix.
REM ============================================================
title Jarvis Doctor
cd /d "%~dp0"

set "PY="
where py >/dev/null 2>/dev/null && set "PY=py -3"
if not defined PY ( where python >/dev/null 2>/dev/null && set "PY=python" )
if not defined PY (
  echo.
  echo  [STOP] Python is not on PATH.
  echo         Install Python 3.11 from python.org and TICK
  echo         "Add Python to PATH" during setup.
  echo.
  pause & exit /b 1
)

%PY% tools\doctor.py
echo.
pause
