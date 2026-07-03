# V8_PHASE1_REPORT.md — Stabilization (partial)

## Scope honesty
The V8 directive requires "Runtime / Windows / Resource-monitoring verification"
for every phase. This build environment is Linux, no network, no display, no
Windows, no Ollama, no GPU. So I implemented the parts that are **pure logic and
verifiable here**, and I am NOT claiming the hardware-dependent parts work — those
are written for you to run and verify on the target box.

## DONE + verified here

### Ollama model management (RAM constraints) — services/ollama_manager.py
- Approved models hard-wired: fast=qwen2.5:0.5b, reasoning=deepseek-r1:1.5b, vision=llava:7b.
- llava flagged LARGE; loaded ONLY in vision(), behind a lock, and unloaded
  (keep_alive=0) immediately after — so two large models never co-reside.
- health(), validate_model() (rejects unapproved + unpulled), retry w/ backoff.
- Verified: 7/7 logic checks pass (approved set, large-lock, graceful degrade,
  rejection of unapproved models, no-raise error strings).
- New routes: GET /agents/ollama/status, /agents/ollama/health.

### Sample fallbacks removed (Phase 1.2 / 1.3)
- clickworker_service.fetch_tasks → returns [] when live scrape empty (no fake categories).
- zuodao_service.fetch_tasks → same. Verified.

### Chat persistence (Phase 1.4)
- Backend already persisted to SQLite chat_messages; the bug was the frontend
  generating a NEW session id every load and never restoring.
- Fixed Chat.jsx: stable session id in localStorage + restores history from
  GET /chat/history/{session} on mount. Survives refresh now.

### Emergency stop (Phase 2 safety, brought forward)
- desktop_agent: _emergency_stop Event; all input actions refuse while engaged;
  file ops still allowed. Routes: POST /agents/desktop/estop, /estop/clear,
  GET /estop/status. Verified: input blocked when engaged, clears correctly.

### True-vision pipeline (Phase 4 groundwork)
- vision_agent.analyze_screen now tries REAL llava vision (sends image pixels)
  and only falls back to OCR→reasoning if llava unavailable. Returns method:
  "llava-vision" or "ocr-fallback" so you can tell which ran.

## WRITTEN for you to verify on Windows (NOT verified here)
- Hubstaff scraper selectors / waits, Clickworker+Zuodao real end-to-end submit,
  Playwright crash recovery & persistent login, executor browser submission,
  live desktop control, llava actually running, RAM behaviour.

## Verified-here checks
- All backend Python compiles. AST imports resolve. All JSX braces+imports OK.
- ollama_manager: 7/7 logic tests. emergency stop: 4/4. (Run directly, real asserts.)

## NOT run (no network): npm/vite build, uvicorn, Ollama, Playwright. Not claimed.
