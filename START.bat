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

REM Confirm the build tool is REALLY there before launching the UI window.
REM "node_modules exists" is not the same question: a ZIP extracted over an old
REM copy leaves the folder without vite in it, and `npm run dev` then dies with
REM "Cannot find module 'vite'" in a window that closes too fast to read.
if not exist "%ROOT%frontend\node_modules\vite\package.json" (
  echo.
  echo  The UI packages are missing or incomplete. Installing them now.
  echo  This takes a few minutes the first time.
  echo.
  pushd "%ROOT%frontend"
  if "%JARVIS_CN%"=="1" (
    call %NPM% install --no-audit --no-fund --registry=https://registry.npmmirror.com
  ) else (
    call %NPM% install --no-audit --no-fund
  )
  popd
)
if not exist "%ROOT%frontend\node_modules\vite\package.json" (
  echo.
  echo  The UI still won't install. Jarvis's backend will start anyway, but
  echo  there will be no web page. Run this by hand to see the real error:
  echo.
  echo      cd /d "%ROOT%frontend"
  echo      npm install --registry=https://registry.npmmirror.com
  echo.
  pause
)

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
echo.
echo  The UI did not answer after 80 seconds.
echo.
echo  Look at the "Jarvis UI" window - the error is in there. The usual one is
echo  "Cannot find module 'vite'", which means the UI packages didn't install.
echo  Fix it with:
echo.
echo      cd /d "%ROOT%frontend"
echo      npm install --registry=https://registry.npmmirror.com
echo.
echo  The backend is still running at http://127.0.0.1:8000 either way.
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
