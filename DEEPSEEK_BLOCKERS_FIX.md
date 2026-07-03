# DeepSeek Integration Blockers - Fix Report

Runtime proof captured by executing the real main.py / routes / ollama_manager
against a FastAPI stub (no network in build env, so uvicorn/curl can't run here;
the stub executes the actual wiring code and enumerates real registered routes).

================================================================================
## BLOCKER 1 - main.py does not mount /agents router
================================================================================
STATUS: ALREADY CORRECT in current code (DeepSeek reviewed an older copy).

Evidence - exact lines in backend/main.py:
  Line 53: from routes.agents       import router as agents_router          # V5
  Line 56: app.include_router(agents_router, prefix="/agents", tags=["Agents"])

RUNTIME PROOF (executed main.py, enumerated app.routes):
  main.py imported successfully - NO silent import failure
  Total routes registered: 123
  /agents routes registered: 46
  Sample: /agents/command, /agents/ollama/models, /agents/vision/analyze,
          /agents/desktop/open-app, /agents/desktop/minimize, ...

================================================================================
## BLOCKER 2 - incorrect imports (routers.* -> routes.*) / silent failures
================================================================================
STATUS: NO 'routers.' typos exist; all route modules import cleanly.

RUNTIME PROOF (imported each module):
  [OK] routes.agents      [OK] routes.proposals   [OK] routes.messages
  [OK] routes.analytics   [OK] routes.scraper     [OK] routes.fiverr
  [OK] routes.hubstaff    [OK] routes.clickworker [OK] routes.zuodao
  [OK] routes.automation  [OK] routes.orchestrator
  11/11 route modules import cleanly
  'routers.' (wrong-name) imports found: 0

Scraper routers proven loaded:
  /hubstaff: 7   /clickworker: 7   /zuodao: 7   /orchestrator: 7   /automation: 12

================================================================================
## BLOCKER 3 - vision() used hardcoded llava:7b (REAL BUG - NOW FIXED)
================================================================================
STATUS: FIXED.

File: backend/services/ollama_manager.py, function vision() (line 230).
BEFORE: validate_model(VISION_MODEL) + _chat_with_retry(VISION_MODEL, ...)
        -> always tried 'llava:7b' even if a different vision model was installed
        and failed hard if llava:7b wasn't pulled.
AFTER (line 239): model = resolve_models()["resolved"]["vision"]
        -> uses the auto-detected installed vision model; clean error if none.

RUNTIME PROOF (3 cases, executed):
  Case A: installed=[deepseek-r1:latest, bakllava:latest, qwen:latest]
          vision() used model = bakllava:latest   (NOT hardcoded llava)
  Case B: installed=[deepseek-r1:latest, qwen:latest]  (no vision model)
          vision() -> {ok:False, error:"No vision model installed..."} (no crash)
  Case C: installed=[llava:7b, qwen:latest]
          vision() used model = llava:7b           (uses it when present)

================================================================================
## FILES CHANGED THIS ROUND
================================================================================
1. backend/services/ollama_manager.py
   - vision() rewritten (line ~230-249) to use resolve_models()["resolved"]["vision"]
   - returns {"model": <resolved>} in the result for traceability
   (Blockers 1 & 2 required NO change - already correct; proven at runtime.)

## HOW TO REPRODUCE PROOF ON YOUR MACHINE (real uvicorn + curl)
  cd backend && python -m uvicorn main:app --port 8000
  curl http://127.0.0.1:8000/agents/ollama/models     # shows resolved models
  curl http://127.0.0.1:8000/agents/status            # agent router live
  curl http://127.0.0.1:8000/hubstaff/jobs            # scraper route loads
  # vision uses detected model:
  curl -X POST http://127.0.0.1:8000/agents/vision/analyze -H "Content-Type: application/json" -d "{}"
