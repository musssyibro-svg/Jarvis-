@echo off
REM ============================================================
REM  JARVIS DOCTOR - run this FIRST when something will not start.
REM  Checks every dependency and the mistakes that produce
REM  misleading errors, then prints exactly what to fix.
REM ============================================================
title Jarvis Doctor
cd /d "%~dp0"

REM Find Python.
REM
REM These lines used to use the Unix null device. Windows cmd then tries to
REM redirect into a folder called \dev, that folder does not exist, so the
REM redirect fails, so the whole command fails and the && never runs. PY was
REM therefore never set, and the launcher announced "Python is not installed"
REM on a machine with a perfectly working Python 3.11.
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY ( where python3 >nul 2>&1 && set "PY=python3" )
REM Last resort: `where` can miss a Python that runs perfectly well (a Store
REM alias, an odd PATH). Ask Python itself before declaring it missing.
if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
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
