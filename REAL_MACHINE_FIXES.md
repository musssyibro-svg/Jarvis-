# REAL MACHINE FIX LIST — Progress & Evidence

## IMPORTANT: evidence I can and cannot produce
This build environment is Linux, headless, no Ollama, no Tesseract, no display,
no network to job sites. The fix list requires screenshots / OCR before-after /
video / live job results — NONE of which can be generated here. Those must come
from your Windows box. What I CAN do: fix the logic and prove it with executable
tests using mocked inputs / real SQLite. Below, each item is marked accordingly.

---

## PHASE 1 — CRITICAL

### #1 Ollama model configuration — FIXED + VERIFIED HERE
Root cause: `deepseek_service.call_model()` used hardcoded OLLAMA_MODEL
('deepseek-r1:1.5b'), which isn't installed → "model not found".
Fix:
- New `ollama_manager.resolve_models()` queries `ollama.list()` and maps
  preferred→installed by exact match, family prefix, role heuristic, fallback.
- `call_model()` now resolves to an installed model and, on failure, tries every
  other installed model before erroring.
- `fast()`/`reason()` use resolved models. New route GET /agents/ollama/models.
- vision resolves to None if no real vision model (won't misuse a text model).
PROOF (ran here with your actual model list):
  installed: deepseek-r1:latest, qwen2:7b, qwen:latest
  reasoning -> deepseek-r1:latest   (was the crashing 'deepseek-r1:1.5b')
  fast      -> qwen:latest          (smaller preferred over qwen2:7b)
  vision    -> None                 (correctly refuses; no llava)
EVIDENCE YOU MUST CAPTURE ON WINDOWS: screenshot of chat answering, settings page.

### #2 MemoryAgent crash — FIXED + VERIFIED HERE
Root cause: `orchestrator.py:151` calls `MemoryAgent().run({})` but the class had
no `run()` method → "'MemoryAgent' object has no attribute 'run'".
Fix: added `MemoryAgent.run()` returning {"insights":{...}, "feed":[...]} built
from existing generate_insights()/get_win_patterns()/get_platform_scores().
PROOF (ran here with real SQLite): MemoryAgent().run({}) returns dict with
insights+feed, best_platform computed, no exception.
EVIDENCE YOU MUST CAPTURE: live feed screenshot showing "Memory updated".

### #3 OCR not working — PARTIAL (path auto-detect done; binary is on you)
Root cause: pytesseract installed but Tesseract.exe not on PATH.
Fix: vision_agent auto-detects tesseract.exe in the 4 common Windows install
locations and sets pytesseract.tesseract_cmd.
REMAINING (your machine): install Tesseract:
  https://github.com/UB-Mannheim/tesseract/wiki  then OCR works from UI.
EVIDENCE YOU MUST CAPTURE: before/after OCR screenshots.

---

## PHASE 2 — DESKTOP

### #4 Desktop expansion — MOSTLY ALREADY PRESENT + minimize/maximize ADDED
Already supported (verified in code): open chrome, edge, calculator, vscode,
explorer, custom programs; close_app; focus_window; type_text; click; screenshots.
NEW this round: minimize_window(), maximize_window() + routes
/agents/desktop/minimize and /maximize.
PROOF: functions exist, compile, degrade gracefully without pygetwindow.
EVIDENCE YOU MUST CAPTURE: screenshots/video of each command on Windows.

### #5 Desktop reliability — ALREADY PRESENT
Every desktop function returns {success, action, error} dicts; commander emits to
the live feed; emergency stop gate present. No code change needed.

---

## PHASE 3-5 — NOT DONE (require your machine / are larger features)
- #6 multi-platform scanners: hubstaff/zuodao have diagnostic logging now; real
  job results require live sites + login. RemoteOK/WeWorkRemotely exist as
  platform modules. Needs your-machine run to confirm real results.
- #7 proposal save/edit/status: DB + routes exist; needs UI verification.
- #8/#9/#10 beginner UI / dashboard / feed: UI work needing your screenshots and
  Grok UX review — not started this round.
- #11 one-button autonomy: orchestrator pipeline exists (and #2 fix unblocks its
  memory stage); full end-to-end demo requires your machine.

---

## FILES CHANGED THIS ROUND
1. backend/services/ollama_manager.py  — resolve_models(), _list_installed(), _resolve()
2. backend/services/deepseek_service.py — call_model() auto-resolves installed model
3. backend/agents/memory_agent.py       — added run() method (#2 crash fix)
4. backend/agents/vision_agent.py        — Tesseract path auto-detect (#3)
5. backend/agents/desktop_agent.py       — minimize_window()/maximize_window() (#4)
6. backend/routes/agents.py              — /ollama/models, /desktop/minimize, /maximize

## VERIFIED HERE (executable proof)
- #1 model resolution: 3/3 mappings correct with your real model list
- #2 MemoryAgent.run(): returns correct shape, real SQLite, no crash
- #4 minimize/maximize: present, compile, graceful degrade
- Full backend: all files compile clean
- Verification suite: runs, 2 PASS / 4 FAIL / 5 SKIP (env-limited, unchanged)

## STILL NEEDS YOUR WINDOWS BOX (cannot fake)
Chat screenshot, settings screenshot, feed screenshot, OCR before/after,
desktop command video, per-platform job screenshots, proposal flow, autonomy demo.
