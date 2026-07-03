# Jarvis — Run Guide (single package)

This package = your V9 backend + the new cinematic Core UI + a live state feed,
all wired together. Phase 4 (SSE) is already applied here — no patching needed.

## What's new in this package vs your last build
- frontend/src/JarvisCore.jsx  — the cinematic Core UI (now the default view)
- backend/routes/orchestrator_feed.py — SSE endpoint /orchestrator/feed
- backend/main.py — feed route registered (already done here)
- App.jsx — Core is the default tab; Chat/Workspace/Dashboard/Settings still there

The feed reuses your EXISTING event bus (agents/orchestrator.py STATE.subscribe).
No emit patch was needed — your orchestrator already fans out events.

## Run (Windows, 16GB)
1. Start Ollama:        ollama serve
2. Backend:             cd backend
                        pip install -r requirements.txt
                        python -m uvicorn main:app --reload --port 8000
   - if that errors with "module not found", run from the parent folder instead:
     python -m uvicorn backend.main:app --reload --port 8000
3. Test the feed:       open http://127.0.0.1:8000/orchestrator/sse
   - you should see:    data: {"ping": true}   then periodic pings
4. Frontend:            cd frontend
                        npm install
                        npm run dev
   - open the printed URL. The Core is the default view.

## What proves it works
- Backend starts: "Uvicorn running on http://127.0.0.1:8000"
- /orchestrator/feed shows {"ping": true}
- In the UI, the Core animates. While the feed is connected but idle it stays calm;
  when you run a command/auto-mode, real agent events drive the Core's state
  (scouting=emerald beam, proposing=amber, executing=amber convergence, etc.)
- If the backend is OFF, the Core falls back to a demo cycle so the UI still looks alive.

## If something fails
- Backend crash on startup -> copy the FULL red traceback. That's the real next task.
- Feed connects but Core never changes on real activity -> the orchestrator may not be
  emitting during your command path; that's a backend wiring check, not a UI issue.

This package is code-complete and compiles. It has NOT been run on a real machine
in this session (no Windows/Ollama/browser here), so the first real run is yours —
and the startup output is the next thing that moves us forward.

## Review fixes applied (this build)
1. Browser commands now route (adapter checked "browse", intent map emits "browser") — was silently broken.
2. ExecutorAgent.is_risky() added — chat no longer crashes on risky actions (delete/close/submit).
3. _decide_planning: bad `fast` import replaced with call_model(..., fast=True) — was an ImportError.
4. _verify: perception failure now = NOT verified (was falsely returning success when it couldn't confirm).
5. STATE.emit: listeners snapshotted under lock, fanout after release — removes deadlock-under-load risk.

## Review round 2 fixes (this build)
A. Fixed remaining `"browse"` check in adapter (line 130) — browser routing now fully works.
C. Command box now POSTs to /chat (was a fake demo box that did nothing) — the Core actually controls Jarvis now.
E. Chat actions route through public execute_action() (act + verify), not private _act() — no longer bypass the safety check.
F. CORS narrowed to localhost origins (wildcard + credentials=True is invalid in strict browsers).
D. OrchestratorCore emits explicit UI state; feed uses it directly instead of guessing from English keywords.

## Known/deferred (not blocking first run)
- /chat is sync; a slow Ollama call blocks that worker. Fine for single-user local; revisit if it stalls.
- No auth on endpoints — acceptable for localhost-only; add a token before any tunnel/remote exposure.

## Review round 4-5 fixes (this build)
- confirm() now routes approved risky actions through execute_action (verify), not bare _act.
- browse stub no longer reports fake success — returns not-implemented (real nav = Phase 5/browser-use).
- _pending dict now lock-protected (request_approval/confirm/cancel/has_pending).
- parse action returns a clear "couldn't interpret" message instead of "unknown action" failure.
- _recover confirmed using plain time.sleep in a background thread (NOT run_until_complete on a
  running loop — that dangerous pattern was a reviewer suggestion, never applied). Correct as-is.

## Phase 5 prep — browser stack (install when ready, China mirrors)
pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple browser-use playwright langchain-ollama
playwright install chromium

## Recommended models for 16GB
ollama pull qwen2.5:1.5b      # always-on chat/fast
ollama pull deepseek-r1:1.5b  # on-demand reasoning
# LLaVA only on demand, unload after use

## OPEN DECISION (only you can make — do NOT let an AI pick):
Two orchestrators still coexist: orchestrator.py (legacy pipeline + event bus) and
orchestrator_core.py (V9 state machine). Recommendation: make OrchestratorCore the one
true brain; keep orchestrator.py ONLY as the STATE event bus (subscribe/emit), delete its
legacy run_pipeline path once you confirm nothing else calls it. This is the last real
architectural debt. Decide after the first successful boot.


## Route collision fixed (important)
The legacy orchestrator router (prefix /orchestrator) already defines /feed, so it
produced /orchestrator/feed — colliding with the new SSE route. The new SSE endpoint
is now /orchestrator/sse (frontend updated to match). Test it at:
    http://127.0.0.1:8000/orchestrator/sse   -> expect data: {"ping": true}

## Dual-orchestrator finding (decision deferred to AFTER boot, on purpose)
Verified statically: run_pipeline() in orchestrator.py is NOT dead code — it powers the
working freelance pipeline via the /orchestrator/start route + scheduler.py. OrchestratorCore
is the newer V9 goal state machine. DO NOT delete run_pipeline blindly; that's your working
freelance feature. Decide which is canonical only after you boot and see which actually runs.
Every importer of orchestrator.py uses only STATE (the event bus), so that part stays regardless.

## Runtime fixes (after first successful boot — from your screenshots)
1. SCREENSHOT: executor called desktop_agent.screenshot() which doesn't exist; now calls
   vision_agent.screenshot(). This works WITHOUT Tesseract — OCR (pytesseract) is only needed
   for reading text from the screen, not for taking the screenshot.
2. EDGE/APPS: browsers live in Windows App Paths, not PATH. open_app now launches msedge/chrome/
   firefox/code via shell 'start' so "Windows cannot find 'edge'" is fixed. Other apps unchanged.
3. SPEED: default fast model set to qwen2:1.5b (you have it; 934MB). deepseek-r1 is reasoning-only,
   on demand. Plain chat now calls call_model(fast=True) instead of the heavy model — big speedup.
4. CORE BUTTONS: left sidebar (Command/Agents/Tasks/Memory/Settings) was static; now clickable.
   Agents panel fetches /agents/status and lists agents + an "Add Agent" placeholder.

## Optional: enable OCR (only if you want Jarvis to READ text from screenshots)
pip install pytesseract pillow
# then install Tesseract binary: https://github.com/UB-Mannheim/tesseract/wiki
# (check "Add to PATH" during install). Screenshots already work without this.

## Adding agents (your goal)
backend/agents/registry.py already exists with register()/get()/list_agents() and even MCP
support. To add a custom agent later: create the agent class, registry.register("name", Cls, {meta}),
and it shows in the Agents panel. No core rewrite needed — this is the foundation for the
agency-agents style roster you saw.

## Fable 5 audit pass (fresh-eyes review of the full build)
Verified: all prior fixes present; /chat correctly routes through the commander adapter
(so typed commands like "screenshot"/"open edge" reach the executor); /health exists;
end-to-end workflow runs to COMPLETE; all 62 backend files compile; 13 modules import clean.

New fixes this pass:
1. FALSE "Could not complete": approved risky actions required visual verification, but
   without Tesseract every verification failed — so actions that WORKED reported failure.
   Now: perception contradiction = fail; perception unavailable = success + honest note.
2. PER-ACTION LAG: every chat desktop command ran full screen analysis (screenshot +
   LLaVA attempt + OCR attempt) afterward. Now gated behind a cached perception
   availability probe — zero cost when OCR/vision isn't installed, per the
   vision-on-demand rule in ARCHITECTURE_LOCK.
3. FUTURE TRAP DEFUSED: requirements.txt installs the pytesseract *package*, but the
   Tesseract *binary* needs the separate Windows installer. The probe now verifies the
   binary itself (get_tesseract_version), so installing requirements won't silently
   re-trigger bug #1. Both branches proven by test.
4. AGENTS PANEL: parses /agents/status's real shape (strings/objects/intent_map) —
   no more junk entries.
5. TASKS PANEL: now lists your scraped jobs from /automation/platform-jobs (title,
   platform, score, link). The scraper was always working — the UI just never showed it.
6. Agent-registry startup failures now log a warning instead of vanishing.
