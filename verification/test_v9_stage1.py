"""
test_v9_stage1.py — Verify V9 Stage 1 control core (LOCKED spec).
1. typed models exist (Goal/WorldState/Action dataclasses)
2. explicit transition table enforced (illegal transition raises)
3. state machine runs goal end-to-end to COMPLETE
4. executor owns approval gate exclusively; loop advances (no spin)
5. commander.normalize_goal returns a typed Goal
6. automation_engine deprecated
"""
import sys
from pathlib import Path
from _harness import TestRun, guard, ROOT

BACKEND = ROOT / "backend"
STUBS   = Path("/tmp/v85_stubs")


def run() -> dict:
    t = TestRun("test_v9_stage1")
    sys.path.insert(0, str(STUBS)); sys.path.insert(0, str(BACKEND))

    # 1. typed models
    def check_models():
        from agents.v9_models import Goal, WorldState, Action
        import dataclasses
        g = Goal(goal_type="freelance_application", objective="EV battery jobs")
        a = Action(action_type="browse", params={"url": "http://x"}, risk_level="low")
        w = WorldState()
        return {"goal_is_dataclass": dataclasses.is_dataclass(g),
                "goal_has_id": bool(g.goal_id),
                "action_has_id": bool(a.action_id),
                "action_risk": a.risk_level,
                "world_retries": w.retries}
    r1 = guard(t, "typed models (Goal/WorldState/Action)", check_models)
    if r1:
        t.check("Goal/WorldState/Action are dataclasses with ids",
                r1["goal_is_dataclass"] and r1["goal_has_id"] and r1["action_has_id"],
                evidence=r1)

    # 2. explicit transition table
    def check_transitions():
        import agents.orchestrator as orch
        orch.STATE.emit = lambda *a, **k: None
        from agents.orchestrator_core import OrchestratorCore, AgentState, TRANSITIONS, IllegalTransition
        oc = OrchestratorCore()
        # IDLE -> SCOUTING is illegal (must go through PLANNING)
        illegal_caught = False
        try:
            oc.transition_state(AgentState.SCOUTING)
        except IllegalTransition:
            illegal_caught = True
        # table completeness
        complete = all(s in TRANSITIONS for s in AgentState)
        return {"illegal_blocked": illegal_caught,
                "table_complete": complete,
                "idle_allows": [s.name for s in TRANSITIONS[AgentState.IDLE]]}
    r2 = guard(t, "explicit transition table enforced", check_transitions)
    if r2:
        t.check("illegal transitions blocked; table covers all states",
                r2["illegal_blocked"] and r2["table_complete"],
                evidence=r2)

    # 3. end-to-end run
    def check_e2e():
        import agents.orchestrator as orch
        orch.STATE.emit = lambda *a, **k: None
        import agents.scout_agent as sa
        sa.ScoutAgent.run = lambda self, ctx: {"jobs":[{"title":"X","url":"http://x/1","platform":"remoteok","relevance_score":0.8}],"feed":[]}
        import agents.proposal_agent as pa
        pa.ProposalAgent.run = lambda self, ctx: {"proposal_text":"hi","confidence_score":0.7}
        import agents.perception_agent as pe
        pe.perception.observe = lambda q="": {"ok":True,"screen_text":"page","method":"stub","elements":[]}
        from agents.orchestrator_core import OrchestratorCore
        from agents.v9_models import Goal
        oc = OrchestratorCore()
        oc.set_goal(Goal(goal_type="freelance_application", objective="X",
                         constraints={"platforms":["remoteok"],"max_jobs":1,"auto_apply":True},
                         success_condition={"min_applied":1}))
        snap = oc.run_full_workflow()
        return {"final_state": snap["state"], "progress": snap["progress"]}
    r3 = guard(t, "state machine end-to-end", check_e2e)
    if r3:
        t.check("goal runs to COMPLETE (progress 100)",
                r3["final_state"]=="COMPLETE" and r3["progress"]==100,
                evidence=r3)

    # 4. executor approval ownership + no spin
    def check_exec():
        import agents.orchestrator as orch
        emitted=[]
        orch.STATE.emit = lambda a,m,l="info": emitted.append(m)
        import agents.perception_agent as pe
        pe.perception.observe = lambda q="": {"ok":True,"screen_text":"p","method":"stub","elements":[]}
        # Stub bid_executor AND the real Playwright launcher so no test path
        # reaches a real browser (this sandbox has no display/Chromium).
        # Patched via sys.modules directly so it holds even if an earlier test
        # in the same process already imported these modules.
        import importlib
        be = importlib.import_module("services.bid_executor")
        be._run_submit = lambda url, text, headless=True: {"success": True, "message": "stub ok"}
        ba = importlib.import_module("agents.browser_agent")
        async def _fake_ctx(headless=True):
            raise RuntimeError("real browser not available in this sandbox")
        ba._get_context = _fake_ctx
        # executor_agent imports bid_executor lazily inside _submit_application,
        # so patching the module object (above) is sufficient — no separate
        # reference to invalidate.
        from agents.executor_agent import ExecutorAgent
        ex = ExecutorAgent()
        out = ex.run_goal({"type":"apply","job":{"title":"X","url":"http://x/1"},
                           "proposal":{"proposal_text":"hi"},"auto_apply":True,"session_id":"s1"})
        submits = sum(1 for e in emitted if "Submitting application" in e)
        owns = all(hasattr(ex,m) for m in ("confirm","cancel","request_approval","has_pending"))
        return {"status": out["status"], "steps": out["steps"],
                "submit_count": submits, "owns_approval": owns}
    r4 = guard(t, "executor owns approval + loop advances", check_exec)
    if r4:
        t.check("executor completes (1 submit, no spin) and owns approval gate",
                r4["status"]=="complete" and r4["submit_count"]==1 and r4["owns_approval"],
                evidence=r4)

    # 5. commander typed Goal
    def check_norm():
        import agents.commander as cmd
        from agents.v9_models import Goal
        g = cmd.normalize_goal("Find 3 EV battery freelance jobs and apply","s1")
        return {"is_goal": isinstance(g, Goal),
                "goal_type": g.goal_type, "approval_required": g.approval_required,
                "max_jobs": g.constraints.get("max_jobs")}
    r5 = guard(t, "commander returns typed Goal", check_norm)
    if r5:
        t.check("chat -> typed Goal (freelance_application, approval_required, max_jobs=3)",
                r5["is_goal"] and r5["goal_type"]=="freelance_application"
                and r5["approval_required"] and r5["max_jobs"]==3,
                evidence=r5)

    # 6. automation_engine deprecated
    def check_dep():
        src = (BACKEND / "services" / "automation_engine.py").read_text(encoding="utf-8")
        return {"deprecated": "DEPRECATED (V9)" in src,
                "first_line": src.strip().splitlines()[0][:80] if src.strip() else ""}
    r6 = guard(t, "automation_engine deprecated", check_dep)
    if r6:
        t.check("automation_engine.py deprecated", r6["deprecated"], evidence=r6)

    # 7. Stage 2 structured perception (find_element logic)
    def check_stage2():
        from agents.perception_agent import perception
        els = [
            {"id":0,"role":"button","tag":"BUTTON","text":"Submit Application","bbox":[100,400,160,40],"clickable":True},
            {"id":1,"role":"paragraph","tag":"P","text":"desc","bbox":[0,0,10,10],"clickable":False},
        ]
        hit = perception.find_element(els, text="Submit Application", clickable_only=True)
        miss = perception.find_element(els, text="desc", clickable_only=True)
        has_methods = all(hasattr(perception, m) for m in ("observe","observe_browser","observe_desktop","find_element"))
        return {"found_submit": bool(hit), "click_point": hit["click_point"] if hit else None,
                "skips_nonclickable": miss is None, "has_stage2_methods": has_methods}
    r7 = guard(t, "stage2 structured perception", check_stage2)
    if r7:
        t.check("Stage 2: find_element locates clickable target + computes click point",
                r7["found_submit"] and r7["click_point"]==[180,420]
                and r7["skips_nonclickable"] and r7["has_stage2_methods"],
                evidence=r7)

    return t.finish()


if __name__ == "__main__":
    run()
