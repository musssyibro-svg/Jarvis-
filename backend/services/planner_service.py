"""
services/planner_service.py — Long-term project planner (Brain-linked).

Distinct from ExecutorAgent's plan->act->verify loop, which orchestrates ONE
task. This tracks multi-step goals across days/weeks:

    Project "mistore" (goal: launch the store)
      1. [done]    supplier import
      2. [doing]   phone catalog + images
      3. [todo]    pricing engine
      4. [todo]    checkout test
      5. [blocked] deploy   (blocked: waiting on domain)

Projects share their name with the Brain's `project` tag, so facts, decisions
and documents saved "for mistore" line up with the mistore plan — one workspace
across knowledge AND execution.

Storage: SQLite in the existing jarvis.db. Goal->steps decomposition uses the
fast LLM when available, with a keyword-template fallback so it still produces
a usable checklist offline / on a fresh machine.
"""
import logging
import re
from datetime import datetime, timezone

from models.db import conn

logger = logging.getLogger("jarvis.planner")

STATUSES = ("todo", "doing", "done", "blocked")

PLANNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,               -- lowercased workspace key (matches brain.project)
    title      TEXT,                         -- human label
    goal       TEXT,
    status     TEXT DEFAULT 'active',        -- active | done | archived
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS plan_steps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES plan_projects(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    text       TEXT NOT NULL,
    status     TEXT DEFAULT 'todo',          -- todo | doing | done | blocked
    note       TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_steps_project ON plan_steps(project_id);
"""


def init_planner() -> None:
    with conn() as db:
        db.executescript(PLANNER_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(name: str) -> str:
    return (name or "").strip().lower()


# ── Goal decomposition ────────────────────────────────────────────────────────

def _fallback_steps(goal: str) -> list[str]:
    """
    Keyword-template decomposition when no LLM is available. Not clever — just
    a sane, editable starting checklist so the feature works offline.
    """
    g = goal.lower()
    if any(w in g for w in ("launch", "deploy", "ship", "release", "store", "website", "site")):
        return ["Define scope and requirements", "Build the core pieces",
                "Integrate data / suppliers / APIs", "Test end to end",
                "Deploy", "Announce / go live"]
    if any(w in g for w in ("research", "study", "paper", "pinn", "battery", "ev", "thesis")):
        return ["Collect sources and papers", "Summarize key findings into the Brain",
                "Identify gaps / open questions", "Run experiments or analysis",
                "Write up results", "Review and revise"]
    if any(w in g for w in ("freelance", "proposal", "bid", "client", "gig")):
        return ["Scan platforms for matching jobs", "Score and shortlist",
                "Draft proposals", "Submit / apply", "Follow up on replies",
                "Deliver the work"]
    return ["Clarify the goal and success criteria", "Break down the main tasks",
            "Do the work", "Review", "Finish and record the outcome"]


def decompose(goal: str) -> list[str]:
    """Turn a goal into an ordered list of concrete steps. Never raises."""
    goal = (goal or "").strip()
    if not goal:
        return []
    try:
        from services.deepseek_service import call_model
        raw = call_model(
            "Break this goal into 4-8 concrete, ordered, actionable steps. "
            "Output ONLY the steps, one per line, no numbering, no preamble.\n\n"
            f"Goal: {goal}", fast=True)
        if raw and not raw.startswith("["):
            steps = []
            for line in raw.splitlines():
                s = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line).strip()
                if s and len(s) > 2:
                    steps.append(s[:200])
            if 2 <= len(steps) <= 20:
                return steps
    except Exception as e:
        logger.warning(f"planner: LLM decompose failed, using fallback: {e}")
    return _fallback_steps(goal)


# ── Public API ────────────────────────────────────────────────────────────────

def create_project(name: str, goal: str = "", title: str = "",
                   auto_steps: bool = True) -> dict:
    init_planner()
    key = _key(name)
    if not key:
        return {"ok": False, "error": "project name required"}
    with conn() as db:
        existing = db.execute("SELECT id FROM plan_projects WHERE name=?", (key,)).fetchone()
        if existing:
            pid = existing["id"]
            db.execute("UPDATE plan_projects SET goal=?, title=?, updated_at=? WHERE id=?",
                       (goal, title or name, _now(), pid))
        else:
            cur = db.execute(
                "INSERT INTO plan_projects(name,title,goal,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (key, title or name, goal, "active", _now(), _now()))
            pid = cur.lastrowid
    steps = decompose(goal) if (auto_steps and goal) else []
    for s in steps:
        add_step(pid, s)
    logger.info(f"planner: project '{key}' ready ({len(steps)} steps)")
    return {"ok": True, "project_id": pid, "name": key, "steps_created": len(steps)}


def add_step(project_id: int, text: str, status: str = "todo") -> dict:
    init_planner()
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty step"}
    status = status if status in STATUSES else "todo"
    with conn() as db:
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 AS n FROM plan_steps WHERE project_id=?",
                         (project_id,)).fetchone()["n"]
        cur = db.execute(
            "INSERT INTO plan_steps(project_id,seq,text,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?)", (project_id, seq, text, status, _now(), _now()))
        db.execute("UPDATE plan_projects SET updated_at=? WHERE id=?", (_now(), project_id))
    return {"ok": True, "step_id": cur.lastrowid, "seq": seq}


def set_step_status(step_id: int, status: str, note: str | None = None) -> dict:
    init_planner()
    if status not in STATUSES:
        return {"ok": False, "error": f"status must be one of {STATUSES}"}
    with conn() as db:
        row = db.execute("SELECT project_id FROM plan_steps WHERE id=?", (step_id,)).fetchone()
        if not row:
            return {"ok": False, "error": f"no step {step_id}"}
        if note is not None:
            db.execute("UPDATE plan_steps SET status=?, note=?, updated_at=? WHERE id=?",
                       (status, note, _now(), step_id))
        else:
            db.execute("UPDATE plan_steps SET status=?, updated_at=? WHERE id=?",
                       (status, _now(), step_id))
        db.execute("UPDATE plan_projects SET updated_at=? WHERE id=?", (_now(), row["project_id"]))
    return {"ok": True, "step_id": step_id, "status": status}


def delete_step(step_id: int) -> dict:
    init_planner()
    with conn() as db:
        cur = db.execute("DELETE FROM plan_steps WHERE id=?", (step_id,))
    return {"ok": cur.rowcount > 0, "deleted": step_id}


def delete_project(project_id: int) -> dict:
    init_planner()
    with conn() as db:
        cur = db.execute("DELETE FROM plan_projects WHERE id=?", (project_id,))
        db.execute("DELETE FROM plan_steps WHERE project_id=?", (project_id,))
    return {"ok": cur.rowcount > 0, "deleted": project_id}


def _project_dict(db, p) -> dict:
    steps = db.execute(
        "SELECT id, seq, text, status, note FROM plan_steps WHERE project_id=? ORDER BY seq",
        (p["id"],)).fetchall()
    steps = [dict(s) for s in steps]
    done = sum(1 for s in steps if s["status"] == "done")
    return {
        "id": p["id"], "name": p["name"], "title": p["title"], "goal": p["goal"],
        "status": p["status"], "updated_at": p["updated_at"],
        "steps": steps, "total": len(steps), "done": done,
        "progress": round(done / len(steps) * 100) if steps else 0,
    }


def get_project(name_or_id) -> dict | None:
    init_planner()
    with conn() as db:
        if isinstance(name_or_id, int) or str(name_or_id).isdigit():
            p = db.execute("SELECT * FROM plan_projects WHERE id=?", (int(name_or_id),)).fetchone()
        else:
            p = db.execute("SELECT * FROM plan_projects WHERE name=?", (_key(name_or_id),)).fetchone()
        return _project_dict(db, p) if p else None


def list_projects() -> list[dict]:
    init_planner()
    with conn() as db:
        rows = db.execute(
            "SELECT * FROM plan_projects ORDER BY (status='active') DESC, updated_at DESC").fetchall()
        return [_project_dict(db, p) for p in rows]


# ── Auto-execution ────────────────────────────────────────────────────────────
# The planner used to STOP after displaying steps. execute_project() closes the
# loop: each todo step is either translated into real desktop/browser actions
# and executed, or (for think-work like "define scope") the LLM produces the
# deliverable text and attaches it to the step. Either way the step advances
# without the user driving every click.

import json as _json
import threading as _threading

_exec_lock = _threading.Lock()
_executing: set[int] = set()

# Actions the planner may run unattended. Deliberately excludes destructive
# primitives (close_app, delete_file, run_command) — those stay human-approved.
_SAFE_ACTIONS = {"open_app", "type_text", "press", "hotkey", "screenshot",
                 "open_url", "wait", "wait_for_window", "focus_window",
                 "click_text", "write_file", "move", "click"}


def _emit(msg: str, level: str = "info"):
    try:
        from agents.orchestrator import STATE
        STATE.emit("planner", msg, level)
    except Exception:
        pass


def _step_to_actions(step_text: str, goal: str) -> dict:
    """
    Ask the LLM whether this step is something the PC can DO right now
    (concrete desktop/browser actions) or think-work to produce as text.
    Returns {"kind": "actions"|"text", "actions": [...]} — never raises.
    """
    try:
        from services.deepseek_service import call_model
        raw = call_model(
            "You control a Windows PC. Decide if this project step is something "
            "you can DO right now with desktop actions, or knowledge work.\n"
            f"Project goal: {goal}\nStep: {step_text}\n\n"
            'If doable, reply ONLY: {"kind":"actions","actions":[{"action":"open_app|open_url|type_text|press|hotkey|screenshot|write_file","params":{...}}]}\n'
            'If knowledge work, reply ONLY: {"kind":"text"}', fast=True)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            d = _json.loads(m.group())
            if d.get("kind") == "actions":
                actions = [a for a in d.get("actions", [])[:8]
                           if a.get("action") in _SAFE_ACTIONS]
                if actions:
                    return {"kind": "actions", "actions": actions}
            return {"kind": "text"}
    except Exception as e:
        logger.warning(f"planner: step classification failed: {e}")
    return {"kind": "text"}


def _do_text_step(step_text: str, goal: str) -> str:
    """Produce the step's deliverable as text (advice, draft, checklist)."""
    try:
        from services.deepseek_service import call_model
        out = call_model(
            f"You are Jarvis executing a project step for the user.\n"
            f"Project goal: {goal}\nStep: {step_text}\n\n"
            f"Produce the actual deliverable/output for this step (concise, "
            f"concrete, immediately usable). Output ONLY the deliverable.")
        if out and not out.startswith("["):
            return out[:2000]
    except Exception:
        pass
    return ""


def execute_project(project_id: int) -> dict:
    """
    Run every todo step of a project, in order. Safe to call from a background
    task. Executable steps run through the desktop chain executor; think-steps
    get their deliverable generated and attached as the step note.
    """
    pid = int(project_id)
    with _exec_lock:
        if pid in _executing:
            return {"ok": False, "error": "project already executing"}
        _executing.add(pid)
    try:
        proj = get_project(pid)
        if not proj:
            return {"ok": False, "error": f"no project {pid}"}
        _emit(f"Auto-executing project '{proj['title']}' "
              f"({sum(1 for s in proj['steps'] if s['status']=='todo')} steps to go)")
        done_ct, blocked_ct = 0, 0
        for step in proj["steps"]:
            if step["status"] not in ("todo", "doing"):
                continue
            set_step_status(step["id"], "doing")
            _emit(f"Step {step['seq']}: {step['text'][:70]}")
            plan = _step_to_actions(step["text"], proj["goal"] or proj["title"])
            if plan["kind"] == "actions":
                try:
                    from agents.desktop_agent import execute_chain
                    result = execute_chain(plan["actions"])
                except Exception as e:
                    result = {"success": False, "error": str(e)}
                if result.get("success"):
                    set_step_status(step["id"], "done",
                                    note=f"executed {len(plan['actions'])} action(s)")
                    _emit(f"Step {step['seq']} done ✓", "success")
                    done_ct += 1
                else:
                    set_step_status(step["id"], "blocked",
                                    note=f"execution failed: {result.get('error','')[:200]}")
                    _emit(f"Step {step['seq']} blocked: {result.get('error','')[:80]}",
                          "warning")
                    blocked_ct += 1
            else:
                deliverable = _do_text_step(step["text"], proj["goal"] or proj["title"])
                if deliverable:
                    set_step_status(step["id"], "done", note=deliverable[:1000])
                    _emit(f"Step {step['seq']} done ✓ (deliverable attached)", "success")
                    done_ct += 1
                else:
                    set_step_status(step["id"], "blocked",
                                    note="needs your input — no LLM available "
                                         "or step requires human judgment")
                    blocked_ct += 1
        _emit(f"Project '{proj['title']}' auto-run finished: "
              f"{done_ct} done, {blocked_ct} blocked",
              "success" if blocked_ct == 0 else "warning")
        return {"ok": True, "done": done_ct, "blocked": blocked_ct}
    finally:
        with _exec_lock:
            _executing.discard(pid)


def is_executing(project_id: int) -> bool:
    with _exec_lock:
        return int(project_id) in _executing


def summary_line() -> str:
    """One-line status of active projects, for chat/status surfaces."""
    projs = [p for p in list_projects() if p["status"] == "active"]
    if not projs:
        return ""
    bits = [f"{p['title']} {p['done']}/{p['total']}" for p in projs[:5]]
    return "Active plans: " + " · ".join(bits)
