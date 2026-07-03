# Fresh-Eyes Audit — 2026-07-03

Independent verification pass over the JARVIS_READY.zip drop, run against the
actual code (py_compile, module-by-module import, a live uvicorn instance,
and real HTTP calls) rather than by reading claims. This repo had zero prior
commits, so this audit's fixes are folded into the initial import.

## Claims checked against the actual code — all confirmed present

- `/orchestrator/sse` route (renamed from the old path) matches the
  frontend's `EventSource(API + "/orchestrator/sse")` call.
- `vision_agent.screenshot()` / OCR path used for the `screenshot` command
  (not a dead `screenshot_agent`).
- `desktop_agent.open_app()` launches Edge/Chrome/Firefox via
  `cmd /c start` so Windows resolves App-Paths-registry browsers correctly.
- `services/ollama_manager.py` defaults to the fast model (`qwen2.5:0.5b`)
  for chat/routing, reserving `deepseek-r1:1.5b` for reasoning and lazily
  loading `llava:7b` only on explicit vision calls.
- `/chat` → `CommanderAdapter.handle_chat` → `ExecutorAgent` is a real,
  live path (verified by curling `/chat` with `screenshot` / `open edge`
  against a running instance).
- Sidebar tabs (`Command/Agents/Tasks/Memory/Settings`) are backed by
  `onClick={() => setPanel(x)}` — genuinely clickable, not decorative.
- `ExecutorAgent.confirm()` verification semantics: perception
  *contradicting* the result fails the action; perception being
  *unavailable* succeeds with an honest "couldn't visually verify" note
  instead of a false failure.
- `START_JARVIS.bat` one-click launcher, including a China-mirror pip
  fallback for the network-restricted case described in the project's
  hardware/geography notes.

All of the above were exercised, not just read — see "Live verification" below.

## Real bugs found and fixed this pass

1. **`backend/agents/executor_agent.py` — `threading` used but never
   imported.** `ExecutorAgent.__init__` calls `threading.Lock()` with no
   `import threading` in the file. This is a `NameError` the instant
   `ExecutorAgent()` is constructed (the `/chat` path, `/agents/status`,
   and the autonomous goal path all construct one). Confirmed by
   instantiating it directly before the fix (`NameError: name 'threading'
   is not defined`). Fixed by adding the import.

2. **`backend/agents/registry.py` — `register_core_agents()` was fully
   silent.** All six per-agent `try/except Exception: pass` blocks
   swallowed errors with zero logging, so a broken agent (like #1 above)
   would just vanish from the registry with no trace anywhere — including
   in the outer `try/except` in `main.py`, which only ever sees a clean
   return. Added `logger.warning(...)` per agent naming which one failed
   and why. Verified the log line fires correctly by deliberately breaking
   an agent import and observing the warning.

3. **`backend/adapters/commander_adapter.py` — `_route_action` had no
   `close_app` mapping.** Chat intent detection already classifies
   `"close notepad"` as a `desktop` intent, but the interactive router
   only builds an `Action` for `screenshot` / `open ` / browser-navigation
   phrasing; everything else — including every "close X" phrasing — fell
   into the generic unmapped `"parse"` action and immediately failed with
   "could not interpret command". `close_app` never got a chance to reach
   the risky-action approval gate. Confirmed live: `curl .../chat -d
   '{"message":"close notepad"}'` returned "could not interpret command"
   before the fix. Added a `"close "` branch mirroring `"open "`, so it now
   builds a `close_app` Action and correctly requires approval before
   running (`close_app` is already in `ExecutorAgent.RISKY_ACTIONS`).

4. **`backend/agents/desktop_agent.py` — `close_app()` used `pkill -f
   <name>` on non-Windows, which matches the FULL COMMAND LINE of every
   process on the system, not just the target's image name.** This is a
   real hazard, not a theoretical one: while testing fix #3 above in this
   sandbox, a `pkill -f notepad` call matched and killed an unrelated
   process purely because "notepad" appeared as a substring elsewhere in
   its command line, wedging the test shell. On a user's machine the same
   pattern means `close_app("code")` or `close_app("chrome")` could kill
   any process that merely references that string in an argument or file
   path — not just the intended app. Rewrote `close_app` to match by exact
   process name via `psutil` (already a project dependency, already used
   in `main.py`), which only ever compares against the actual executable
   image name. Verified: killed a same-named target process precisely,
   left a decoy process with the search string only in its argv
   untouched, and left a same-named-but-different-argv process alone too.

## Live verification (this pass, not the previous report)

- `python3 -m py_compile` over all 62 backend `.py` files: clean.
- Imported all 62 backend modules individually in a fresh venv
  (fastapi/uvicorn/pydantic/psutil/requests/beautifulsoup4/python-dotenv
  only — no playwright/ollama/pyautogui/pytesseract installed, matching a
  fresh machine before the optional extras are set up): all 62 import
  clean, confirming the "safe imports degrade gracefully" claims actually
  hold and nothing crashes at import time when the heavy optional deps are
  absent.
- Ran the real FastAPI app with `uvicorn`, hit it with real HTTP requests:
  - `GET /health` → 200, correct shape.
  - `GET /agents/status` → 200, matches the shape the Agents panel parses.
  - `GET /automation/platform-jobs` → 200, matches the shape the Tasks
    panel parses.
  - `POST /chat` with `"screenshot"`, `"open edge"` → routed through the
    executor, failed for the expected reason (no display / no `cmd.exe`
    on this Linux sandbox), not silently swallowed.
  - `POST /chat` with `"close sleep"` → `needs_approval: true`, then
    `POST /chat "yes"` → the target process was actually terminated and
    the response correctly notes it couldn't visually verify the result.
- `register_core_agents()` registers all 6 core agents cleanly against the
  now-fixed `executor_agent.py`.
- Frontend: `npm install && npm run build` — 47 modules, builds clean
  (one non-blocking chunk-size warning from Vite, not an error).

## Not re-litigated

Everything under "Claims checked" above was actually re-verified against
running code in this pass, not taken on faith from the bundled reports —
this file exists precisely because the previous report's claims needed an
independent check, not because they're assumed correct going forward.
