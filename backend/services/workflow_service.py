"""
services/workflow_service.py — teach a task once, replay it by name forever.

The user's ask: "I want to add any freelancer or web task, and it automatically
learns what I want and adds it to my jobs — no need for me to do anything."

A workflow is a named, saved sequence of concrete steps. You teach it in plain
language ("open notepad, type my address, save it"), Jarvis resolves that into
executable steps (via the Tool Registry first, the LLM only if needed), and
stores it. Later, "run my <name>" replays the whole thing through the VERIFIED
execution engine — so it's confirmed, retried, and honest about success.

This is the self-learning layer the roadmaps kept asking for, kept deliberately
simple: no capture-by-observation magic, just teach-by-telling + reliable replay.
"""
import json
from datetime import datetime, timezone

from models.db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    description TEXT,
    steps_json  TEXT NOT NULL,
    source_text TEXT,
    runs        INTEGER DEFAULT 0,
    last_run    TEXT,
    last_status TEXT,
    created_at  TEXT
);
"""


def init_workflows() -> None:
    with conn() as db:
        db.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(name: str) -> str:
    return (name or "").strip().lower()


# ── Teaching ──────────────────────────────────────────────────────────────────

def _resolve_to_steps(text: str) -> list[dict]:
    """
    Turn a natural-language task into executable steps. Tool Registry first
    (deterministic), then the LLM for anything it doesn't recognise. Splits on
    'then' / ',' / newlines so multi-part instructions each get resolved.
    """
    from services.tool_registry import resolve_steps
    steps: list[dict] = []

    # whole-string shortcut (e.g. "open qq and check messages")
    whole = resolve_steps(text)
    if whole:
        return whole

    import re
    # Split into clauses on then / comma / newline so each part resolves cleanly
    # ("open notepad, type hello" -> "open notepad" + "type hello"). A single
    # clause with "and" ("open notepad and type hello") is handled whole by the
    # command parser below.
    parts = [p.strip() for p in re.split(r"\bthen\b|[,\n;]", text) if p.strip()]
    for part in parts:
        r = resolve_steps(part)
        if r:
            steps.extend(r)
            continue
        try:
            from adapters.commander_adapter import _parse_command_steps
            parsed = _parse_command_steps(part)
            if parsed:
                steps.extend({"action": a.action_type, "params": a.params or {}}
                             for a in parsed)
                continue
        except Exception:
            pass
        # LLM fallback for a single clause
        steps.extend(_llm_steps(part))
    return steps


def _llm_steps(clause: str) -> list[dict]:
    try:
        from services.deepseek_service import call_model
        import re
        raw = call_model(
            "Convert this ONE desktop instruction into JSON steps. Allowed actions:\n"
            '  open_app{"name_or_path"} close_app{"process_name"} type_text{"text"}\n'
            '  press{"key"} hotkey{"keys":[]} screenshot{} analyze{"question"}\n'
            '  open_url{"url"} click_text{"text"} write_file{"path","content"}\n'
            'Reply ONLY: {"steps":[{"action":"...","params":{...}}]}\n'
            f"Instruction: {clause}", fast=True)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return []
        allowed = {"open_app", "close_app", "type_text", "press", "hotkey",
                   "screenshot", "analyze", "open_url", "click_text", "write_file"}
        return [s for s in json.loads(m.group()).get("steps", [])[:8]
                if s.get("action") in allowed]
    except Exception:
        return []


def teach(name: str, source_text: str = "", steps: list | None = None,
          description: str = "") -> dict:
    """Create/replace a workflow from natural language or explicit steps."""
    init_workflows()
    key = _key(name)
    if not key:
        return {"ok": False, "error": "workflow name required"}
    if steps is None:
        steps = _resolve_to_steps(source_text)
    if not steps:
        return {"ok": False, "error": "couldn't turn that into any runnable steps — "
                "try wording it like 'open notepad, type hello, save'"}
    with conn() as db:
        db.execute(
            "INSERT INTO workflows(name,description,steps_json,source_text,created_at) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET steps_json=excluded.steps_json, "
            "description=excluded.description, source_text=excluded.source_text",
            (key, description or source_text[:80], json.dumps(steps), source_text, _now()))
    return {"ok": True, "name": key, "steps": steps, "step_count": len(steps)}


# ── Running ───────────────────────────────────────────────────────────────────

def get(name: str) -> dict | None:
    init_workflows()
    with conn() as db:
        row = db.execute("SELECT * FROM workflows WHERE name=?", (_key(name),)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["steps"] = json.loads(d.get("steps_json") or "[]")
    except Exception:
        d["steps"] = []
    return d


def run(name: str) -> dict:
    """Replay a workflow through the verified execution engine."""
    wf = get(name)
    if not wf:
        return {"ok": False, "error": f"no workflow named '{name}'"}
    try:
        from agents.orchestrator import STATE
        STATE.emit("workflow", f"Running your workflow '{wf['name']}' "
                   f"({len(wf['steps'])} steps)")
    except Exception:
        pass
    from agents.desktop_agent import execute_chain
    result = execute_chain(wf["steps"])
    status = "done" if result.get("success") else "failed"
    with conn() as db:
        db.execute("UPDATE workflows SET runs=runs+1, last_run=?, last_status=? WHERE name=?",
                   (_now(), status, _key(name)))
    try:
        from agents.orchestrator import STATE
        STATE.emit("workflow",
                   f"Workflow '{wf['name']}' {status}"
                   + ("" if result.get("success") else f": {result.get('error','')}"),
                   "success" if result.get("success") else "error")
    except Exception:
        pass
    return {"ok": result.get("success", False), "status": status,
            "name": wf["name"], "result": result}


def list_workflows() -> list[dict]:
    init_workflows()
    with conn() as db:
        rows = db.execute("SELECT id,name,description,steps_json,runs,last_run,last_status,"
                          "created_at FROM workflows ORDER BY name").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["step_count"] = len(json.loads(d.pop("steps_json") or "[]"))
        except Exception:
            d["step_count"] = 0
        out.append(d)
    return out


def delete(name: str) -> dict:
    init_workflows()
    with conn() as db:
        cur = db.execute("DELETE FROM workflows WHERE name=?", (_key(name),))
    return {"ok": cur.rowcount > 0}


def find_run_command(message: str) -> str | None:
    """
    Detect "run my <name>", "run <name> workflow", "do my <name>" in chat and
    return the workflow name if it exists. Lets the commander replay by voice.
    """
    import re
    m = re.match(r"^\s*(?:run|do|execute|start)\s+(?:my\s+)?(.+?)"
                 r"(?:\s+(?:workflow|task|routine))?\s*$", (message or ""), re.I)
    if not m:
        return None
    cand = _key(m.group(1))
    # exact or prefix match against known workflows
    names = [w["name"] for w in list_workflows()]
    if cand in names:
        return cand
    for n in names:
        if cand and (cand in n or n in cand):
            return n
    return None
