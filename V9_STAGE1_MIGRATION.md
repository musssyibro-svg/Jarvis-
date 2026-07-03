# Jarvis V9 Stage 1 — Migration Record (LOCKED spec)

## New files
- backend/agents/v9_models.py        — typed Goal / WorldState / Action dataclasses
- backend/agents/orchestrator_core.py — state machine + EXPLICIT transition table
- backend/agents/executor_agent.py    — autonomy loop; EXCLUSIVELY owns approval gate
- backend/agents/perception_agent.py  — Stage 1 perception (text); Stage 2 = structured

## Modified files
- backend/agents/commander.py   — normalize_goal() returns a typed Goal (chat adapter only)
- backend/agents/scheduler.py   — drives OrchestratorCore.run_full_workflow()
- backend/main.py               — POST /v9/goal, GET /v9/state
- backend/services/automation_engine.py — DEPRECATED banner

## Mandatory data models (enforced)
Goal(goal_id, goal_type, objective, constraints, approval_required, success_condition, created_at)
WorldState(jobs, proposals, active_job, retries, screen_state)
Action(action_id, action_type, params, verify_condition, risk_level)

## State machine transition table (enforced; illegal transitions raise)
IDLE       -> PLANNING
PLANNING   -> SCOUTING | FAILED
SCOUTING   -> PROPOSING | FAILED | COMPLETE
PROPOSING  -> EXECUTING | FAILED | COMPLETE
EXECUTING  -> VERIFYING | RECOVERING
VERIFYING  -> COMPLETE | RECOVERING
RECOVERING -> EXECUTING | FAILED

## Locked rules honored
- Commander outputs Goal objects only; owns NO execution/orchestration/approval state.
- ExecutorAgent EXCLUSIVELY owns pending actions, confirm, cancel, approval gate, retry.

## Migration checklist
- [x] typed models (Goal/WorldState/Action)
- [x] orchestrator_core state machine + explicit transition table
- [x] executor_agent typed Action + exclusive approval ownership
- [x] perception_agent Stage 1
- [x] commander -> smart adapter (typed Goal)
- [x] scheduler -> OrchestratorCore
- [x] automation_engine deprecated
- [x] verification: test_v9_stage1 (6/6 checks pass)

## Verified here (deterministic, against stubs)
- typed dataclasses with ids
- illegal transitions blocked; table covers all 9 states
- goal runs end-to-end IDLE->...->COMPLETE (progress 100)
- executor: 1 submit, no spin; owns approval gate (confirm/cancel/request_approval/has_pending)
- commander: "Find 3 ... apply" -> typed Goal, max_jobs=3, approval_required=True
- automation_engine deprecated; full backend compiles; test_v85_wiring still PASS

## Bugs found & fixed during build
- executor decide-loop spin (repeated submit) -> phase tracker; now advances
- commander regex double-escape (max_jobs always 5) -> fixed; extracts correctly
- test cross-contamination (v85 stub leaked into v9) -> restore real class in finally

## NOT proven here (your Windows box)
Real perception (Stage 1 is text-only), live job applications, "feels autonomous".
Capability estimate per spec: Stage 1 ~70-75% structural; real-world needs Stage 2 perception.
