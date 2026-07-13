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


def summary_line() -> str:
    """One-line status of active projects, for chat/status surfaces."""
    projs = [p for p in list_projects() if p["status"] == "active"]
    if not projs:
        return ""
    bits = [f"{p['title']} {p['done']}/{p['total']}" for p in projs[:5]]
    return "Active plans: " + " · ".join(bits)
