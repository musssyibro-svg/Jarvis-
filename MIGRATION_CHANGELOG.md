# Jarvis V9 Phase 2 — Migration Changelog

## Step A — extract CommanderAdapter (Hard Constraint 1 triggered)
handle_message was tightly coupled to execute_command (4 sites) + create_plan,
so per the hard rule, chat entry was EXTRACTED to adapters/commander_adapter.py
instead of patching commander.py. /chat and /agents/command repointed to it.

## Step B — suite check: restored to baseline 4/4/5 (updated chat-routing test).

## Step C — repo grep: confirmed remaining planner/execute_command references were
only inside commander's (now-dead) functions + comments; no live external callers
after repointing /command, the read-only plan routes, and the 4 workflow routes.

## Step D — deletions
- rm agents/planner.py
- removed execute_command (149 lines), execute_plan (62), handle_message (139)
  from commander.py (469 -> 127 lines). Kept detect_intent, is_risky,
  normalize_goal, get_status, INTENT_MAP, CONFIRM_PHRASES (used by adapter/routes).
- read-only plan routes now read agent_plans table directly (no planner import).

## Step E — suite: 4/4/5 restored (updated approval-gate test to use ExecutorAgent,
the new owner of the gate, instead of the deleted handle_message).

## Step F — ExecutorAgent._act rewired to desktop_agent primitives directly.
NO commander fallback. Emits visible SSE per action (UX guardrail A).

## Step G — control-flow report produced (CONTROL_FLOW_REPORT.md).

## Registry hooks (non-blocking)
- agents/registry.py: AgentRegistry (register/get/list/enable/health_check) +
  register_core_agents() for desktop/browser/executor/perception/scout/proposal.
- MCP-compatible metadata (name/permissions/source/health_status).
- Extensibility + MCP hooks present as deferred stubs (signatures only).

## Browser ownership (Constraint 4)
- core/browser_lock.py: non-blocking single-owner lock. Wired into bid_executor.
  2nd workflow gets "browser busy" immediately.

## Verification baseline held at every step: 4 PASS / 4 FAIL / 5 SKIP.
(The 4 FAIL / 5 SKIP are pre-existing no-backend/no-Ollama/no-display sandbox
results, identical to the pre-migration baseline.)
