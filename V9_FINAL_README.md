# Jarvis V9 — Final Package

## 1. Project tree
See FINAL_PROJECT_TREE_backend.txt and FINAL_PROJECT_TREE_frontend.txt
(full file lists, generated from the actual package contents).

Key V9 files:
  backend/adapters/commander_adapter.py   - chat entry point (no execution)
  backend/agents/orchestrator_core.py     - state machine brain
  backend/agents/executor_agent.py        - autonomy loop (observe/decide/act/verify/recover)
  backend/agents/perception_agent.py      - Stage 1 text + Stage 2 structured DOM/OCR
  backend/agents/v9_models.py             - typed Goal/WorldState/Action
  backend/agents/registry.py              - agent registry (MCP-compatible hooks)
  backend/core/browser_lock.py            - single-owner browser lock
  backend/services/bid_executor.py        - real job submission (retry, no fake success)
  backend/agents/commander.py             - reduced to detect_intent/normalize_goal/is_risky only

## 2. Windows setup (exact steps)
1. Install Python 3.11+, Node 18+, Ollama for Windows.
2. ollama pull deepseek-r1          (and any other model you intend to use)
3. cd backend
   pip install -r requirements.txt
4. python -m playwright install chromium
5. (Optional, for desktop OCR-with-boxes) install Tesseract for Windows,
   ensure tesseract.exe is on PATH.
6. cd ../frontend
   npm install

## 3. Run
Terminal 1:  ollama serve
Terminal 2:  cd backend  && python -m uvicorn main:app --port 8000
Terminal 3:  cd frontend && npm run dev      (open the printed URL)

## 4. Required dependencies
Backend (see backend/requirements.txt for exact pinned versions):
  fastapi, uvicorn, pydantic, python-dotenv, schedule, playwright,
  pytesseract, Pillow, requests, sqlite3 (stdlib)
Frontend: React, Vite (see frontend/package.json)
External: Ollama (local LLM runtime), Tesseract OCR (optional, for desktop bbox perception)

## 5. Known limitations (honest, as of this package)
- submit_application now calls real bid_executor/_run_submit with retry, but
  has NOT been run against a real job site from this environment — first real
  use should be watched closely.
- observe_browser() (Stage 2 DOM extraction) has not been executed against a
  real Playwright page — only verified with mock element data.
- ExecutorAgent._decide() branches for browser/vision/file/memory/planning are
  implemented but only unit-verified with stubs, not run end-to-end live.
- Chrome alias resolution for open_app("chrome") was unreliable in earlier
  testing on the target machine; Notepad and screenshot were reliable.
- Login-gated platforms (Hubstaff/Clickworker/Zuodao) return 0 jobs until you
  log in once via the agent's browser profile.
- This package was built and compiled in a sandbox with no display/Ollama/
  network/Chromium — all compilation and unit-level logic is verified there;
  no live runtime test has been performed by Claude. Your machine is the
  first place this code will actually run end-to-end.
