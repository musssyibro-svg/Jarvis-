@echo off
REM ==============================================================
REM  JARVIS - press this. That is the whole instruction.
REM
REM  Installs anything missing (Python packages, the automation
REM  browser, UI packages, AI models), then starts the backend and
REM  the UI and opens Jarvis in your browser.
REM
REM  Safe to run every time. Everything already installed is
REM  skipped, so later runs take seconds.
REM ==============================================================
title Jarvis
cd /d "%~dp0"
set "ROOT=%~dp0"

REM China mirrors. Without these the Playwright browser download and
REM npm install do not fail fast - they hang for minutes, which looks
REM exactly like a broken launcher. Set JARVIS_CN=0 to use upstream.
if not defined JARVIS_CN set "JARVIS_CN=1"
if "%JARVIS_CN%"=="1" (
  set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
  set "NPM_CONFIG_REGISTRY=https://registry.npmmirror.com"
)

set "PY="
where py >/dev/null 2>/dev/null && set "PY=py -3"
if not defined PY ( where python >/dev/null 2>/dev/null && set "PY=python" )
if not defined PY (
  echo.
  echo  Python is not installed, or not on PATH.
  echo.
  echo  Install Python 3.11 from python.org and TICK the box that says
  echo  "Add Python to PATH" during setup. Then run this file again.
  echo.
  pause & exit /b 1
)

REM ---- install everything that is missing ----
%PY% tools\setup.py
if errorlevel 1 (
  echo.
  echo  Setup reported problems ^(listed above^).
  echo  Jarvis will still try to start - press a key to continue,
  echo  or close this window to fix them first.
  echo.
  pause
)

REM ---- backend ----
echo.
echo  Starting Jarvis backend...
start "Jarvis Backend" cmd /k "cd /d ""%ROOT%backend"" && %PY% -m uvicorn main:app --port 8000"

REM ---- frontend ----
set "NPM=npm"
where npm >/dev/null 2>/dev/null || set "NPM=npm.cmd"
echo  Starting Jarvis UI...
start "Jarvis UI" cmd /k "cd /d ""%ROOT%frontend"" && %NPM% run dev"

REM ---- wait for the UI, then open it ----
echo  Waiting for the UI...
set /a tries=0
:wait
timeout /t 2 >nul
set /a tries+=1
curl -s http://localhost:5173 >/dev/null 2>nul
if not errorlevel 1 goto ready
curl -s http://localhost:5174 >/dev/null 2>nul
if not errorlevel 1 ( set "UIPORT=5174" & goto ready2 )
if %tries% lss 40 goto wait
echo  The UI did not answer after 80 seconds.
echo  Look at the "Jarvis UI" window for the error.
goto done

:ready
set "UIPORT=5173"
:ready2
start "" http://localhost:%UIPORT%

:done
echo.
echo  ==============================================================
echo    Jarvis is running.
echo      UI        http://localhost:%UIPORT%
echo      Backend   http://127.0.0.1:8000
echo.
echo    Two windows opened. Closing them stops Jarvis.
echo    This window can be closed now.
echo  ==============================================================
echo.
timeout /t 15
