@echo off
REM This launcher is gone. It was the old V8 one and it pulled the wrong
REM models, skipped the UI install, and never checked anything.
REM
REM There is exactly one launcher now:  START.bat
title Jarvis
cd /d "%~dp0"
echo.
echo   START_JARVIS.bat has been replaced by START.bat.
echo.
echo   Starting START.bat for you now...
echo.
timeout /t 3 >nul
call "%~dp0START.bat"
