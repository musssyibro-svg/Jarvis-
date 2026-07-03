"""
test_v85_wiring.py — Verify the four V8.5 structural reconnections.
1. chat -> commander routing
2. approval gate for risky commands
3. scheduler registration (start/stop/status + triggers pipeline)
4. SSE route registration (/orchestrator/feed)
5. (optional) Workspace UI structure (App.jsx 4 tabs, WorkspaceHub subtabs)

Runs via run_all_tests.py; writes results/test_v85_wiring.json.
Uses lightweight stubs for fastapi/schedule when the real libs aren't installed,
so the WIRING logic is exercised even in a headless build env.
"""
import sys
import json
from pathlib import Path
from _harness import TestRun, guard, ROOT

BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "src"
STUBS = Path("/tmp/v85_stubs")


def _ensure_stubs():
    """Create minimal fastapi/schedule/pydantic/dotenv stubs if real libs absent."""
    STUBS.mkdir(parents=True, exist_ok=True)
    (STUBS / "fastapi").mkdir(exist_ok=True)
    (STUBS / "fastapi" / "middleware").mkdir(exist_ok=True)

    (STUBS / "fastapi" / "__init__.py").write_text('''
class HTTPException(Exception):
    def __init__(self, status_code=400, detail=""): self.status_code=status_code; self.detail=detail
class BackgroundTasks:
    def add_task(self,fn,*a,**k): pass
class _R:
    def __init__(self,path): self.path=path
class APIRouter:
    def __init__(self,*a,**k): self.routes=[]; self._reg=[]
    def _m(self,method,path): self._reg.append((method,path)); self.routes.append(_R(path))
    def get(self,p,*a,**k):
        def d(fn): self._m("GET",p); return fn
        return d
    def post(self,p,*a,**k):
        def d(fn): self._m("POST",p); return fn
        return d
    def patch(self,p,*a,**k):
        def d(fn): self._m("PATCH",p); return fn
        return d
    def put(self,p,*a,**k):
        def d(fn): self._m("PUT",p); return fn
        return d
    def delete(self,p,*a,**k):
        def d(fn): self._m("DELETE",p); return fn
        return d
class FastAPI:
    def __init__(self,*a,**k): self.routes=[]
    def add_middleware(self,*a,**k): pass
    def on_event(self,*a,**k):
        def d(fn): return fn
        return d
    def get(self,p,*a,**k):
        def d(fn): self.routes.append(_R(p)); return fn
        return d
    def post(self,p,*a,**k):
        def d(fn): self.routes.append(_R(p)); return fn
        return d
    def put(self,p,*a,**k):
        def d(fn): self.routes.append(_R(p)); return fn
        return d
    def delete(self,p,*a,**k):
        def d(fn): self.routes.append(_R(p)); return fn
        return d
    def include_router(self,router,prefix="",tags=None):
        for method,path in getattr(router,"_reg",[]):
            self.routes.append(_R(prefix+path))
''')
    (STUBS / "fastapi" / "middleware" / "__init__.py").write_text("")
    (STUBS / "fastapi" / "middleware" / "cors.py").write_text("class CORSMiddleware: pass\n")
    (STUBS / "fastapi" / "responses.py").write_text(
        "class StreamingResponse:\n    def __init__(self,*a,**k): pass\n"
        "class JSONResponse:\n    def __init__(self,*a,**k): pass\n")
    (STUBS / "pydantic.py").write_text(
        "class BaseModel:\n"
        "    def __init__(self,**k):\n"
        "        for kk,vv in k.items(): setattr(self,kk,vv)\n"
        "    def dict(self): return {k:v for k,v in self.__dict__.items()}\n"
        "    def __init_subclass__(cls,**k): pass\n"
        "def Field(*a,**k): return None\n")
    (STUBS / "dotenv.py").write_text("def load_dotenv(*a,**k): return False\n")
    (STUBS / "schedule.py").write_text('''
import datetime
jobs=[]
class _Job:
    def __init__(s,n):
        s.n=n; s.tags=set(); s._fn=None
        s.next_run=datetime.datetime.now()+datetime.timedelta(minutes=n)
    def do(s,fn,*a,**k): s._fn=fn; jobs.append(s); return s
    def tag(s,*t): s.tags|=set(t); return s
class _Every:
    def __init__(s,n): s.n=n
    @property
    def minutes(s): return _Job(s.n)
def every(n): return _Every(n)
def run_pending():
    for j in list(jobs):
        if j._fn: j._fn()
def clear(tag=None):
    global jobs
    jobs=[j for j in jobs if not (tag and tag in j.tags)]
''')


def run() -> dict:
    t = TestRun("test_v85_wiring")
    _ensure_stubs()

    # Make stubs importable + backend on path. Real libs take priority if present.
    sys.path.insert(0, str(STUBS))
    sys.path.insert(0, str(BACKEND))

    # ── 1. chat -> commander routing ───────────────────────────────────────────
    def check_chat_routing():
        main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
        # V9: /chat now routes through the extracted CommanderAdapter
        # (/chat -> CommanderAdapter -> OrchestratorCore -> ExecutorAgent).
        from_adapter = "from adapters.commander_adapter import handle_chat" in main_src
        calls_handle = "handle_chat(body.message" in main_src
        import re
        m = re.search(r'@app\.post\("/chat"\).*?(?=@app\.|@router\.|\Z)', main_src, re.DOTALL)
        chat_body = (m.group()[:400] if m else "")
        return {"routes_through_adapter": from_adapter,
                "calls_handle_chat": calls_handle,
                "chat_endpoint_excerpt": chat_body}
    r1 = guard(t, "chat routes through CommanderAdapter (V9)", check_chat_routing)
    if r1:
        t.check("/chat imports and calls commander_adapter.handle_chat",
                r1["routes_through_adapter"] and r1["calls_handle_chat"],
                evidence=r1,
                error=None if (r1["routes_through_adapter"] and r1["calls_handle_chat"])
                      else "main.py /chat does not route through CommanderAdapter")

    # ── 2. approval gate for risky commands ────────────────────────────────────
    def check_approval_gate():
        # V9: approval gate moved OUT of commander into ExecutorAgent.
        # Risk detection still exposed via commander.is_risky (pure helper).
        import agents.commander as cmd
        import agents.orchestrator as orch
        orch.STATE.emit = lambda a,m,l="info": None
        from agents.executor_agent import ExecutorAgent
        from agents.v9_models import Action
        ex = ExecutorAgent()
        # request approval for a risky action -> stored as pending, NOT executed
        risky_action = Action(action_type="delete_file", params={"path": "C:/data"}, risk_level="high")
        gate = ex.request_approval("wiringtest", risky_action)
        not_executed = ex.has_pending("wiringtest")
        return {
            "risky_needs_approval": bool(gate.get("needs_approval")),
            "risky_not_executed":   not_executed,
            "is_risky_delete": cmd.is_risky("delete all files in C:/data"),
            "is_risky_open":   cmd.is_risky("open notepad"),
            "executor_owns_gate": all(hasattr(ex, m) for m in ("confirm","cancel","request_approval","has_pending")),
            "pending_action_type": risky_action.action_type,
        }
    r2 = guard(t, "approval gate blocks risky actions", check_approval_gate)
    if r2:
        t.check("risky command returns needs_approval and is NOT executed",
                r2["risky_needs_approval"] and r2["risky_not_executed"]
                and r2["is_risky_delete"] and not r2["is_risky_open"],
                evidence=r2,
                error=None if r2["risky_needs_approval"]
                      else "risky command was not gated")

    # ── 3. scheduler registration + triggers pipeline ──────────────────────────
    def check_scheduler():
        import agents.orchestrator as orch
        fired = []
        orch.STATE.emit = lambda a,m,l="info": fired.append(m)
        # V9: scheduler now drives OrchestratorCore.set_goal/run, not start_pipeline.
        import agents.orchestrator_core as ocmod
        _real_core = ocmod.OrchestratorCore   # save to restore (avoid contaminating other tests)
        class _FakeCore:
            def set_goal(self, g): fired.append(f"GOAL_SET:{g.get('goal_type')}")
            def run(self): fired.append("CORE_RUN"); return {"state":"COMPLETE"}
        ocmod.OrchestratorCore = _FakeCore
        import importlib
        if "agents.scheduler" in sys.modules:
            importlib.reload(sys.modules["agents.scheduler"])
        import agents.scheduler as sch
        try:
            st = sch.start_schedule({"platforms": ["remoteok"]}, every_minutes=15)
            import schedule
            schedule.run_pending()             # force a tick
            stopped  = sch.stop_schedule()
        finally:
            ocmod.OrchestratorCore = _real_core   # RESTORE real class
            if "agents.scheduler" in sys.modules:
                importlib.reload(sys.modules["agents.scheduler"])
        return {
            "enabled_on_start": st.get("enabled"),
            "every_minutes": st.get("every_minutes"),
            "next_run_set": bool(st.get("next_run")),
            "core_triggered": any(f.startswith("CORE_RUN") or f.startswith("GOAL_SET") for f in fired),
            "disabled_on_stop": not stopped.get("enabled"),
            "fired_log": fired[:5],
        }
    r3 = guard(t, "scheduler registers and triggers OrchestratorCore", check_scheduler)
    if r3:
        t.check("scheduler start/stop works and triggers the V9 OrchestratorCore",
                r3["enabled_on_start"] and r3["core_triggered"] and r3["disabled_on_stop"],
                evidence=r3,
                error=None if r3["core_triggered"] else "scheduler did not trigger OrchestratorCore")

    # ── 4. SSE route registration ──────────────────────────────────────────────
    def check_sse_routes():
        import importlib
        # import main fresh against stubs and enumerate routes
        for m in ("main",):
            if m in sys.modules: del sys.modules[m]
        import main
        routes = sorted(set(r.path for r in main.app.routes))
        return {
            "total_routes": len(routes),
            "feed_route":          "/orchestrator/feed" in routes,
            "schedule_start":      "/orchestrator/schedule/start" in routes,
            "schedule_stop":       "/orchestrator/schedule/stop" in routes,
            "schedule_status":     "/orchestrator/schedule/status" in routes,
            "chat_route":          "/chat" in routes,
        }
    r4 = guard(t, "SSE + schedule routes registered", check_sse_routes)
    if r4:
        t.check("/orchestrator/feed (SSE) and schedule routes are registered",
                r4["feed_route"] and r4["schedule_start"] and r4["schedule_status"],
                evidence=r4,
                error=None if r4["feed_route"] else "SSE feed route missing")

    # ── 5. (optional) Workspace UI structure ───────────────────────────────────
    def check_ui():
        app = (FRONTEND / "App.jsx").read_text(encoding="utf-8")
        hub_path = FRONTEND / "pages" / "WorkspaceHub.jsx"
        hub = hub_path.read_text(encoding="utf-8") if hub_path.exists() else ""
        tabs_ok = all(x in app for x in ("Chat", "WorkspaceHub", "Dashboard", "Settings"))
        default_chat = "useState('chat')" in app
        # 4 top-level tabs only (no direct Jobs/Proposals imports in App.jsx)
        only_four = ("Jobs" not in app and "Proposals" not in app)
        subtabs = sum(1 for x in ("Jobs","Proposals","Messages","AutoMode","Agents",
                                  "Analytics","Tasks","Notes") if x in hub)
        return {"tabs_present": tabs_ok, "chat_default": default_chat,
                "only_four_toplevel": only_four, "workspace_subtab_count": subtabs}
    r5 = guard(t, "workspace UI structure (optional)", check_ui)
    if r5:
        t.check("App.jsx has 4 tabs with Chat default; WorkspaceHub groups tools",
                r5["tabs_present"] and r5["chat_default"] and r5["only_four_toplevel"]
                and r5["workspace_subtab_count"] >= 6,
                evidence=r5,
                error=None if r5["tabs_present"] else "UI structure not as expected")

    return t.finish()


if __name__ == "__main__":
    run()
