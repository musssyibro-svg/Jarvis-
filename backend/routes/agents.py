"""
backend/routes/agents.py
Agent API: Commander, Desktop, Vision, Planner, Memory
All heavy work routes through CommanderAgent.
"""
import threading
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class CommandRequest(BaseModel):
    message:    str
    session_id: str = "default"

class ActionRequest(BaseModel):
    action: str
    params: dict = {}

class PlanRequest(BaseModel):
    goal:    str
    context: str = ""
    execute: bool = False   # if True, run the plan immediately

class MemoryStoreRequest(BaseModel):
    key:   str
    value: str

class OutcomeRequest(BaseModel):
    platform:         str
    job_type:         str
    proposal_snippet: str
    won:              bool
    client_response:  str = ""
    notes:            str = ""

class DesktopActionRequest(BaseModel):
    action: str   # click, type, hotkey, open_app, etc.
    x:      Optional[int]   = None
    y:      Optional[int]   = None
    text:   Optional[str]   = None
    keys:   Optional[list]  = None
    app:    Optional[str]   = None
    url:    Optional[str]   = None
    path:   Optional[str]   = None
    content:Optional[str]   = None


# ── Commander ─────────────────────────────────────────────────────────────────

@router.get("/status")
def commander_status():
    from agents.commander import get_status
    return get_status()

@router.post("/command")
def send_command(body: CommandRequest, background_tasks: BackgroundTasks):
    """Route a natural language command through the V9 CommanderAdapter."""
    from adapters.commander_adapter import handle_chat
    result = handle_chat(body.message, body.session_id)
    return result

@router.post("/execute")
def execute_action(body: ActionRequest):
    """
    V9: single-action execution now routes through ExecutorAgent (which owns the
    action loop + approval gate), NOT commander.execute_command directly.
    This keeps OrchestratorCore/Executor as the single source of workflow state.
    """
    from agents.executor_agent import ExecutorAgent
    from agents.v9_models import Action
    ex = ExecutorAgent()
    action = Action(action_type=body.action, params=body.params or {})
    result = ex._act(action)   # primitive action via the executor's own dispatch
    return result


# ── Desktop ───────────────────────────────────────────────────────────────────

@router.get("/desktop/status")
def desktop_status():
    from agents.desktop_agent import get_status
    return get_status()

@router.post("/desktop/screenshot")
def take_screenshot():
    from agents.vision_agent import screenshot
    return screenshot()

@router.post("/desktop/click")
def desktop_click(body: DesktopActionRequest):
    from agents.desktop_agent import click
    if body.x is None or body.y is None:
        raise HTTPException(400, "x and y required for click")
    return click(body.x, body.y)

@router.post("/desktop/type")
def desktop_type(body: DesktopActionRequest):
    from agents.desktop_agent import type_text_raw
    if not body.text:
        raise HTTPException(400, "text required")
    return type_text_raw(body.text)

@router.post("/desktop/hotkey")
def desktop_hotkey(body: DesktopActionRequest):
    from agents.desktop_agent import hotkey
    if not body.keys:
        raise HTTPException(400, "keys required")
    return hotkey(*body.keys)

@router.post("/desktop/open-app")
def desktop_open_app(body: DesktopActionRequest):
    from agents.desktop_agent import open_app
    if not body.app:
        raise HTTPException(400, "app required")
    return open_app(body.app)

@router.post("/desktop/close-app")
def desktop_close_app(body: dict):
    from agents.desktop_agent import close_app
    name = body.get("app") or body.get("process_name")
    if not name:
        raise HTTPException(400, "app/process_name required")
    return close_app(name)

@router.post("/desktop/switch-window")
def desktop_switch_window(body: dict):
    from agents.desktop_agent import switch_window
    if not body.get("title"):
        raise HTTPException(400, "title required")
    return switch_window(body["title"])

@router.post("/desktop/open-folder")
def desktop_open_folder(body: dict):
    from agents.desktop_agent import open_folder
    if not body.get("path"):
        raise HTTPException(400, "path required")
    return open_folder(body["path"])

@router.post("/desktop/search-files")
def desktop_search_files(body: dict):
    from agents.desktop_agent import search_files
    return search_files(body.get("directory","."), body.get("query",""), body.get("max_results",50))

@router.post("/desktop/rename-file")
def desktop_rename_file(body: dict):
    from agents.desktop_agent import rename_file
    return rename_file(body.get("old_path",""), body.get("new_name",""))

@router.post("/desktop/move-file")
def desktop_move_file(body: dict):
    from agents.desktop_agent import move_file
    return move_file(body.get("src",""), body.get("dest_dir",""))

@router.post("/desktop/copy-file")
def desktop_copy_file(body: dict):
    from agents.desktop_agent import copy_file
    return copy_file(body.get("src",""), body.get("dest",""))

@router.post("/desktop/delete-file")
def desktop_delete_file(body: dict):
    from agents.desktop_agent import delete_file
    return delete_file(body.get("path",""), body.get("confirm", False))

@router.post("/desktop/open-url")
def desktop_open_url(body: DesktopActionRequest):
    from agents.desktop_agent import open_url
    if not body.url:
        raise HTTPException(400, "url required")
    return open_url(body.url)

@router.get("/desktop/windows")
def list_windows():
    from agents.desktop_agent import list_windows
    return list_windows()

@router.post("/desktop/read-file")
def read_file(body: DesktopActionRequest):
    from agents.desktop_agent import read_file as rf
    if not body.path:
        raise HTTPException(400, "path required")
    return rf(body.path)

@router.post("/desktop/write-file")
def write_file(body: DesktopActionRequest):
    from agents.desktop_agent import write_file as wf
    if not body.path or body.content is None:
        raise HTTPException(400, "path and content required")
    return wf(body.path, body.content)


# ── Vision ────────────────────────────────────────────────────────────────────

@router.get("/vision/status")
def vision_status():
    from agents.vision_agent import get_status
    return get_status()

@router.post("/vision/screenshot")
def vision_screenshot():
    from agents.vision_agent import screenshot
    result = screenshot()
    # Don't return raw b64 in list — just path and metadata
    result.pop("b64", None)
    return result

@router.post("/vision/ocr")
def vision_ocr():
    from agents.vision_agent import ocr_screen
    return ocr_screen()

@router.post("/vision/find-text")
def vision_find_text(body: dict):
    from agents.vision_agent import find_text_on_screen
    return find_text_on_screen(body.get("text",""))

@router.post("/vision/analyze")
def vision_analyze(body: dict):
    from agents.vision_agent import analyze_screen
    result = analyze_screen(question=body.get("question","What is on the screen?"))
    result.pop("b64", None)
    return result

@router.post("/vision/locate-text")
def vision_locate_text(body: dict):
    """Word-level OCR: returns screen coordinates of the text (for clicking)."""
    from agents.vision_agent import locate_text_coords
    return locate_text_coords(body.get("text",""))

@router.post("/vision/click-text")
def vision_click_text(body: dict):
    """See → act: find the text on screen and click it."""
    from agents.vision_agent import click_text
    if not body.get("text"):
        raise HTTPException(400, "text required")
    return click_text(body["text"])


# ── Chained desktop execution (multi-step, atomic) ───────────────────────────

@router.post("/desktop/chain")
def desktop_chain(body: dict):
    """
    Run a SEQUENCE of desktop steps as one task:
      {"steps": [{"action":"open_app","params":{"name_or_path":"notepad"}},
                 {"action":"type_text","params":{"text":"hello"}},
                 {"action":"hotkey","params":{"keys":["ctrl","s"]}}]}
    Waits for windows between steps; stops and reports on first failure.
    """
    from agents.desktop_agent import execute_chain
    steps = body.get("steps") or []
    if not steps:
        raise HTTPException(400, "steps required")
    return execute_chain(steps)


# ── Planner ───────────────────────────────────────────────────────────────────

@router.post("/planner/create")
def create_plan(body: PlanRequest, background_tasks: BackgroundTasks):
    """
    V9: planning is no longer a separate one-shot planner. A goal is handed to
    OrchestratorCore, which owns PLANNING as a state. planner.py is being retired.
    """
    from agents.v9_models import Goal
    from agents.orchestrator_core import OrchestratorCore
    goal = Goal(goal_type="task", objective=body.goal,
                constraints={"context": body.context},
                approval_required=False)
    core = OrchestratorCore()
    core.set_goal(goal)
    if body.execute:
        background_tasks.add_task(core.run_full_workflow)
        return {"goal_id": goal.goal_id, "goal": goal.to_dict(), "executing": True}
    return {"goal_id": goal.goal_id, "goal": goal.to_dict(), "executing": False}

@router.post("/planner/{plan_id}/execute")
def execute_plan_route(plan_id: int, background_tasks: BackgroundTasks):
    """
    V9: legacy plan execution retired. Plans persisted under the old planner are
    read-only history; new execution must go through POST /v9/goal or
    /agents/planner/create. Returns 410 to signal the path moved.
    """
    raise HTTPException(410, "Legacy plan execution removed in V9. "
                             "Use POST /v9/goal or /agents/planner/create.")

@router.get("/planner/plans")
def list_plans():
    """V9: plans are read-only history from agent_plans (planner.py retired)."""
    from models.db import conn
    with conn() as db:
        rows = db.execute("SELECT id, goal, status, current_step, created_at "
                          "FROM agent_plans ORDER BY id DESC").fetchall()
    return {"plans": [dict(r) for r in rows]}

@router.get("/planner/{plan_id}")
def get_plan_route(plan_id: int):
    """V9: read-only plan history from agent_plans (planner.py retired)."""
    from models.db import conn
    with conn() as db:
        row = db.execute("SELECT * FROM agent_plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Plan not found")
    return {"success": True, "plan": dict(row)}


# ── Memory ────────────────────────────────────────────────────────────────────

@router.get("/memory/status")
def memory_status():
    from agents.memory_agent import MemoryAgent
    return {
        "win_patterns":  len(MemoryAgent.get_win_patterns()),
        "fail_patterns": len(MemoryAgent.get_fail_patterns()),
        "platforms":     MemoryAgent.get_platform_scores(),
        "kv_count":      len(MemoryAgent.get_all_kv()),
    }

@router.get("/memory/insights")
def memory_insights():
    from agents.memory_agent import MemoryAgent
    return MemoryAgent.generate_insights()

@router.get("/memory/patterns")
def memory_patterns(won: Optional[bool] = None):
    from agents.memory_agent import MemoryAgent
    if won is True:
        return {"patterns": MemoryAgent.get_win_patterns()}
    if won is False:
        return {"patterns": MemoryAgent.get_fail_patterns()}
    return {
        "wins":  MemoryAgent.get_win_patterns(),
        "fails": MemoryAgent.get_fail_patterns(),
    }

@router.post("/memory/outcome")
def record_outcome(body: OutcomeRequest):
    from agents.memory_agent import MemoryAgent
    MemoryAgent.record_outcome(body.platform, body.job_type, body.proposal_snippet, body.won, body.client_response, body.notes)
    return {"success": True}

@router.get("/memory/history")
def action_history(agent: Optional[str] = None, limit: int = 50):
    from agents.memory_agent import MemoryAgent
    return {"history": MemoryAgent.get_action_history(agent, limit)}

@router.post("/memory/store")
def memory_store(body: MemoryStoreRequest):
    from agents.memory_agent import MemoryAgent
    MemoryAgent.store(body.key, body.value)
    return {"success": True, "key": body.key}

@router.get("/memory/recall/{key}")
def memory_recall(key: str):
    from agents.memory_agent import MemoryAgent
    value = MemoryAgent.recall(key)
    if value is None:
        raise HTTPException(404, f"Key '{key}' not found in memory")
    return {"key": key, "value": value}

@router.get("/memory/all")
def memory_all():
    from agents.memory_agent import MemoryAgent
    return MemoryAgent.get_all_kv()

# ── Agent Registry: add/remove/run custom agents at runtime ───────────────────

class InstallAgentRequest(BaseModel):
    name: str
    code: str
    description: str = ""

@router.get("/registry")
def registry_list():
    """All registered agents (built-in + custom) with metadata + enabled state."""
    from agents.registry import registry, AGENT_TEMPLATE
    out = []
    for name, entry in registry.list_agents().items():
        meta = dict(entry["metadata"])
        out.append({"name": name, "enabled": entry["enabled"],
                    "source": meta.get("source", "internal"),
                    "kind": meta.get("kind", ""),
                    "description": meta.get("description", ""),
                    "permissions": meta.get("permissions", []),
                    "registered_at": meta.get("registered_at", "")})
    return {"agents": out, "template": AGENT_TEMPLATE}

@router.post("/registry/install")
def registry_install(body: InstallAgentRequest):
    """Paste Python code → live agent. Persisted to agents/custom/ + DB."""
    from agents.registry import registry
    r = registry.install_from_code(body.name, body.code, body.description)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "install failed"))
    return r

@router.post("/registry/{name}/toggle")
def registry_toggle(name: str, body: dict = None):
    from agents.registry import registry
    entry = registry.list_agents().get(name)
    if not entry:
        raise HTTPException(404, f"agent '{name}' not found")
    on = not entry["enabled"] if body is None or "enabled" not in (body or {}) \
         else bool(body["enabled"])
    registry.enable(name, on)
    if entry["metadata"].get("source") == "custom":
        try:
            from models.db import conn
            with conn() as db:
                db.execute("UPDATE custom_agents SET enabled=? WHERE name=?",
                           (1 if on else 0, name))
        except Exception:
            pass
    return {"ok": True, "name": name, "enabled": on}

@router.delete("/registry/{name}")
def registry_uninstall(name: str):
    from agents.registry import registry
    r = registry.uninstall(name)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "uninstall failed"))
    return r

@router.post("/registry/{name}/run")
def registry_run(name: str, body: dict = None):
    """Run any registered agent directly with a context dict."""
    from agents.registry import registry
    return registry.run_agent(name, (body or {}).get("context", body or {}))


@router.get("/tools")
def list_tools():
    """Deterministic action shortcuts the Tool Registry resolves without the LLM."""
    from services.tool_registry import list_tools
    return {"tools": list_tools()}


# ── Ollama health + model management (V8) ────────────────────────────────────
@router.get("/ollama/status")
def ollama_status():
    from services.ollama_manager import status
    return status()

@router.get("/ollama/health")
def ollama_health():
    from services.ollama_manager import health
    return health()

# ── Emergency stop (V8 Phase 2 safety) ───────────────────────────────────────
@router.post("/desktop/estop")
def desktop_estop():
    from agents.desktop_agent import emergency_stop
    return emergency_stop()

@router.post("/desktop/estop/clear")
def desktop_estop_clear():
    from agents.desktop_agent import clear_emergency_stop
    return clear_emergency_stop()

@router.get("/desktop/estop/status")
def desktop_estop_status():
    from agents.desktop_agent import is_estopped
    return {"emergency_stop": is_estopped()}

@router.get("/ollama/models")
def ollama_models():
    """Auto-detected + resolved model mapping (for Settings page)."""
    from services.ollama_manager import resolve_models
    return resolve_models()

@router.post("/desktop/minimize")
def desktop_minimize(body: dict):
    from agents.desktop_agent import minimize_window
    if not body.get("title"):
        raise HTTPException(400, "title required")
    return minimize_window(body["title"])

@router.post("/desktop/maximize")
def desktop_maximize(body: dict):
    from agents.desktop_agent import maximize_window
    if not body.get("title"):
        raise HTTPException(400, "title required")
    return maximize_window(body["title"])
