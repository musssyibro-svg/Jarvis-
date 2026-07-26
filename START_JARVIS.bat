@echo off
REM ============================================================
REM  JARVIS — true one-click start (backend + UI + browser)
REM  Double-click this file. Nothing else needs to be run.
REM ============================================================
title Jarvis Launcher
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%~dp0"

echo.
echo  ===============================================
echo    JARVIS - starting
echo  ===============================================
echo.

REM ---------- 0. China mirrors ----------
REM Playwright downloads its browser from a Google-hosted CDN and pip/npm from
REM hosts that are slow or unreachable behind the GFW. Without these, install
REM doesn't fail fast - it hangs for minutes and then gives up, which looks
REM exactly like "the launcher is broken".
REM Set JARVIS_CN=0 in your environment to use the upstream sources instead.
if not defined JARVIS_CN set "JARVIS_CN=1"
if "%JARVIS_CN%"=="1" (
  set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
  set "PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
  set "PIP_TRUSTED_HOST=mirrors.tuna.tsinghua.edu.cn"
  set "NPM_CONFIG_REGISTRY=https://registry.npmmirror.com"
  echo  [ok] China mirrors enabled ^(set JARVIS_CN=0 to disable^)
)

REM ---------- 1. Python ----------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo  [X] Python not found on PATH.
  echo      Install Python 3.11+ from python.org and TICK "Add Python to PATH".
  echo.
  pause & exit /b 1
)
echo  [ok] Python: %PY%

REM ---------- 2. Node / npm ----------
REM npm is npm.cmd — `where npm` can miss it in some shells, so check both.
set "NPM="
where npm >nul 2>nul && set "NPM=npm"
if not defined NPM ( where npm.cmd >nul 2>nul && set "NPM=npm.cmd" )
if not defined NPM (
  echo  [X] Node.js / npm not found on PATH.  ^<-- this is why the UI never opened
  echo      Install Node.js LTS from nodejs.org, then re-run this file.
  echo.
  pause & exit /b 1
)
echo  [ok] npm found

REM ---------- 3. Ollama ----------
curl -s http://127.0.0.1:11434/api/tags >nul 2>nul
if errorlevel 1 (
  echo  [..] Ollama not responding - starting it
  start "Ollama" /min cmd /c "ollama serve"
  timeout /t 4 >nul
) else (
  echo  [ok] Ollama already running
)

REM ---------- 4. Backend deps ----------
echo  [..] Backend dependencies
pushd "%ROOT%backend"
%PY% -m pip install -q -r requirements.txt 2>nul
if errorlevel 1 (
  echo       mirror failed - retrying against PyPI directly
  %PY% -m pip install -q --index-url https://pypi.org/simple -r requirements.txt 2>nul
)
popd

REM ---------- 4b. Playwright browser ----------
REM Every freelance login, job scan and bid submission drives this browser.
REM It is NOT installed by `pip install playwright` - it is a separate download,
REM and without it those features fail at runtime with no obvious cause.
%PY% -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); p.chromium.executable_path; p.stop()" >nul 2>nul
if errorlevel 1 (
  echo  [..] Downloading the automation browser ^(first run only^)
  %PY% -m playwright install chromium
  if errorlevel 1 (
    echo  [!] Browser download failed. Freelance automation will not work until it
    echo      succeeds. Retry manually with:
    echo          set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
    echo          %PY% -m playwright install chromium
  )
) else (
  echo  [ok] Automation browser present
)

REM ---------- 5. Backend ----------
echo  [..] Starting backend on http://127.0.0.1:8000
start "Jarvis Backend" cmd /k "cd /d ""%ROOT%backend"" && %PY% -m uvicorn main:app --port 8000"

REM ---------- 6. Frontend deps ----------
if not exist "%ROOT%frontend\node_modules" (
  echo  [..] Installing UI packages ^(first run only, few minutes^)
  pushd "%ROOT%frontend"
  call %NPM% install
  if errorlevel 1 (
    echo       mirror failed - retrying against the npm registry directly
    call %NPM% install --registry=https://registry.npmjs.org
  )
  popd
)

REM ---------- 7. Frontend ----------
echo  [..] Starting UI on http://localhost:5173
start "Jarvis UI" cmd /k "cd /d ""%ROOT%frontend"" && %NPM% run dev"

REM ---------- 8. Wait for the UI, then open the browser ----------
echo  [..] Waiting for the UI to come up...
set /a tries=0
:waitloop
timeout /t 2 >nul
set /a tries+=1
curl -s http://localhost:5173 >nul 2>nul
if not errorlevel 1 goto ready
if %tries% lss 30 goto waitloop
echo  [!] UI didn't answer on :5173 after 60s. Check the "Jarvis UI" window for errors.
goto done

:ready
echo  [ok] UI is up - opening browser
start "" http://localhost:5173

:done
echo.
echo  ===============================================
echo    Jarvis is running.
echo      UI       http://localhost:5173
echo      Backend  http://127.0.0.1:8000
echo      Docs     http://127.0.0.1:8000/api/docs
echo.
echo    Two windows opened (Backend + UI). Closing
echo    them stops Jarvis. This window can be closed.
echo  ===============================================
echo.
timeout /t 10
