# Jarvis V9 — Post-Migration Control-Flow Report (Step G)

## Claim: every workflow path converges on OrchestratorCore / ExecutorAgent.

| Entry point | Routes to | Evidence |
|---|---|---|
| POST /chat | CommanderAdapter.handle_chat -> OrchestratorCore / ExecutorAgent | main.py:131 |
| POST /agents/command | CommanderAdapter.handle_chat | routes/agents.py:63 |
| POST /agents/execute | ExecutorAgent._act (single action via executor) | routes/agents.py:68 |
| POST /agents/planner/create | OrchestratorCore.set_goal + run_full_workflow | routes/agents.py |
| POST /agents/planner/{id}/execute | HTTP 410 (legacy removed) | routes/agents.py |
| POST /automation/start | OrchestratorCore (Goal) | routes/automation.py:22 |
| POST /orchestrator/start | OrchestratorCore (Goal) | routes/orchestrator.py:28 |
| POST /v9/goal | OrchestratorCore.run_full_workflow | main.py:227 |
| Scheduler tick | OrchestratorCore.run_full_workflow | agents/scheduler.py:44 |

## Chat flow (mandatory, achieved)
/chat -> CommanderAdapter -> OrchestratorCore / ExecutorAgent -> DesktopAgent/BrowserAgent
Zero direct desktop/browser execution inside the chat handler. The adapter does
intent detection + goal normalization + memory + SSE + inline approval only.

## Legacy removal (confirmed)
- agents/planner.py: DELETED.
- commander.execute_command / execute_plan / handle_message: REMOVED
  (commander.py 469 -> 127 lines; grep count of those defs = 0).
- ExecutorAgent._act: NO commander fallback; dispatches to desktop_agent directly.
- services/automation_engine.run_auto_mode: no live route calls it (deprecated).
- agents/orchestrator.start_pipeline: no live route calls it (STATE/SSE preserved).

## Single source of truth
OrchestratorCore owns goal + state + WorldState + retries + progress. No parallel
workflow state remains in commander (now adapter-only/pure helpers), planner
(deleted), automation_engine (deprecated), or queue/browser controllers (the
browser is now guarded by core/browser_lock.py single-owner lock).

## Desktop primitive routes
KEPT (per decision): the 20+ /agents/desktop/* primitive routes remain as manual/
debug tools and as the ExecutorAgent's action vocabulary. Only the 4 *workflow*
routes were repointed. This was a deliberate scope choice, not an oversight.

## Verified here (deterministic, stubs)
- Executor _act -> desktop_agent.open_app/screenshot directly, emits
  "[Executor] Opening notepad" SSE, zero commander references.
- Verification suite: 4 PASS / 4 FAIL / 5 SKIP (baseline held across every step).

## NOT proven here (your Windows box)
The 4 runtime chat commands (open notepad, open chrome, check hubstaff, start
autonomous mode) and their screenshots/SSE need a real display + Ollama + browser.
Architecture/wiring is proven; runtime behavior is yours to confirm.
