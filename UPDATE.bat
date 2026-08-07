@echo off
REM ==============================================================
REM  Get the newest Jarvis.
REM
REM  Works whether or not this folder is a git checkout, and never
REM  touches your database, your logins or your settings.
REM ==============================================================
title Jarvis Update
cd /d "%~dp0"

REM Find Python.
REM
REM These lines used to use the Unix null device. Windows cmd then tries to
REM redirect into a folder called \dev, that folder does not exist, so the
REM redirect fails, so the whole command fails and the && never runs. PY was
REM therefore never set, and the launcher announced "Python is not installed"
REM on a machine with a perfectly working Python 3.11.
REM Every candidate is tested by RUNNING it, never by asking whether the
REM command exists. "where py" succeeds whenever the Python launcher is
REM installed, but the launcher can point at an interpreter that is gone:
REM on this machine "py -3" resolved to C:\Python314\python.exe and died
REM with "Unable to create process", while plain "python" was a healthy
REM 3.11.9 sitting right there on PATH. Existence is not the question.
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY ( py -3 --version >nul 2>&1 && set "PY=py -3" )
if not defined PY ( python3 --version >nul 2>&1 && set "PY=python3" )
if not defined PY ( py --version >nul 2>&1 && set "PY=py" )
if not defined PY (
  echo.
  echo   Python is not installed, or not on PATH.
  echo   Install Python 3.11 from python.org, tick "Add Python to PATH".
  echo.
  pause ^& exit /b 1
)

%PY% tools\update.py
echo.
pause
