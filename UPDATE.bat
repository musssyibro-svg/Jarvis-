@echo off
REM ==============================================================
REM  Get the newest Jarvis.
REM
REM  Works whether or not this folder is a git checkout, and never
REM  touches your database, your logins or your settings.
REM ==============================================================
title Jarvis Update
cd /d "%~dp0"

set "PY="
where py >/dev/null 2>/dev/null && set "PY=py -3"
if not defined PY ( where python >/dev/null 2>/dev/null && set "PY=python" )
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
