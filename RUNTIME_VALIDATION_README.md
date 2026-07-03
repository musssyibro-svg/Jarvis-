# V9 Runtime Validation — your 5-minute checkpoint

I cannot run this — it needs your Windows desktop, Ollama, and a real screen.
This harness makes it one command for you, and produces the exact artifacts your
checkpoint requires (SSE logs, before/after screenshots, error traces).

## Steps
1. Start Ollama (so chat/model calls work):  `ollama serve`
2. Double-click `RUN_VALIDATION.bat`  (or: `cd backend && python ..\RUNTIME_VALIDATION.py`)
3. It runs the 4 commands through the REAL V9 stack:
   - open notepad      -> ExecutorAgent._act -> desktop_agent.open_app
   - open chrome       -> same path
   - take a screenshot -> desktop_agent.screenshot
   - start autonomous mode -> CommanderAdapter -> OrchestratorCore
4. Find the `runtime_validation_<timestamp>/` folder it creates.
5. Send back: `sse_log.txt`, `results.json`, and the `*.png` files.

## What proves success
- Notepad and Chrome actually open on screen
- sse_log.txt shows lines like:  [executor] [Executor] Opening notepad (info)
- before/after PNGs differ (the app appeared)
- results.json shows "ok": true per command

## If something fails
results.json will contain the full Python traceback under "error". Send it as-is
— that trace tells me exactly what to fix (e.g. Chrome alias not resolving, which
was a known issue: 'chrome' may need a full path or different alias on your box).

## Known watch-points (from earlier audits)
- Edge/Chrome aliases sometimes fail to resolve -> open_app may need the .exe path.
- 'start autonomous mode' will scan platforms; ones needing login (Hubstaff etc.)
  return 0 jobs until you've logged in once via the browser profile.
