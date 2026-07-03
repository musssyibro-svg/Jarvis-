@echo off
REM Runtime validation for the 4 required V9 commands.
REM Run this on the Windows target with Ollama running.
echo ============================================
echo  Jarvis V9 Runtime Validation
echo  Opens Notepad + Chrome, screenshots, auto mode
echo ============================================
cd /d "%~dp0backend"
python ..\RUNTIME_VALIDATION.py
echo.
echo Artifacts written to a runtime_validation_* folder above.
echo Send back: sse_log.txt, results.json, and the PNG screenshots.
pause
