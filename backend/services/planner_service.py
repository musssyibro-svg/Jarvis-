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
import json as _json
import logging
import re
import threading as _threading
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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES plan_projects(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    status      TEXT DEFAULT 'todo',          -- todo | doing | done | blocked
    note        TEXT,
    action_json TEXT,                         -- concrete desktop action(s) when known deterministically
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_steps_project ON plan_steps(project_id);
"""


def init_planner() -> None:
    with conn() as db:
        db.executescript(PLANNER_SCHEMA)
        # Migrate older DBs that predate action_json.
        try:
            cols = [r[1] for r in db.execute("PRAGMA table_info(plan_steps)").fetchall()]
            if "action_json" not in cols:
                db.execute("ALTER TABLE plan_steps ADD COLUMN action_json TEXT")
        except Exception:
            pass


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


def _registry_steps(goal: str) -> list[dict] | None:
    """
    Known-command shortcut: if the goal is something the Tool Registry
    recognises ("open qq and check messages"), return concrete
    {text, action} step dicts — no LLM, no hallucination. Else None.
    """
    try:
        from services.tool_registry import resolve_steps
        actions = resolve_steps(goal)
    except Exception:
        actions = None
    if not actions:
        return None
    labels = {
        "open_app":        lambda p: f"Open {p.get('name_or_path','app')}",
        "wait_for_window": lambda p: f"Wait for {p.get('title','the window')} to appear",
        "screenshot":      lambda p: "Take a screenshot of the screen",
        "analyze":         lambda p: "Read and summarise what's on the screen",
        "type_text":       lambda p: f"Type: {p.get('text','')[:40]}",
        "press":           lambda p: f"Press {p.get('key','')}",
        "hotkey":          lambda p: f"Press {'+'.join(p.get('keys',[]))}",
        "click_text":      lambda p: f"Click '{p.get('text','')}'",
        "open_url":        lambda p: f"Open {p.get('url','')}",
    }
    steps = []
    for a in actions:
        act = a.get("action", "")
        params = a.get("params", {})
        label = labels.get(act)
        text = label(params) if label else act.replace("_", " ")
        steps.append({"text": text, "action": [a]})
    return steps


def decompose(goal: str) -> list[str]:
    """Turn a goal into an ordered list of concrete steps. Never raises."""
    goal = (goal or "").strip()
    if not goal:
        return []
    reg = _registry_steps(goal)
    if reg:
        return [s["text"] for s in reg]
    try:
        from services.deepseek_service import call_model
        raw = call_model(
            "You are planning steps to run on a WINDOWS DESKTOP PC that you control "
            "directly (you can open apps, type, click, screenshot). "
            "Break this goal into 3-6 concrete desktop steps. "
            "HARD RULES: never write phone/mobile steps ('open your phone', 'tap "
            "Apps'), never invent website signup/login steps unless the goal asks, "
            "never say 'Douyin'. If the goal is 'open <app> and ask X', the steps are: "
            "open the app, wait for it, type X, press Enter. "
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
    # Known commands become concrete, executable steps (no LLM hallucination).
    reg = _registry_steps(goal) if (auto_steps and goal) else None
    if reg:
        for s in reg:
            add_step(pid, s["text"], action=s["action"])
        n = len(reg)
    else:
        steps = decompose(goal) if (auto_steps and goal) else []
        for s in steps:
            add_step(pid, s)
        n = len(steps)
    logger.info(f"planner: project '{key}' ready ({n} steps)")
    return {"ok": True, "project_id": pid, "name": key, "steps_created": n}


def add_step(project_id: int, text: str, status: str = "todo",
             action: list | dict | None = None) -> dict:
    init_planner()
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty step"}
    status = status if status in STATUSES else "todo"
    action_json = _json.dumps(action) if action else None
    with conn() as db:
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 AS n FROM plan_steps WHERE project_id=?",
                         (project_id,)).fetchone()["n"]
        cur = db.execute(
            "INSERT INTO plan_steps(project_id,seq,text,status,action_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)", (project_id, seq, text, status, action_json, _now(), _now()))
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
    # Manually completing the last step should self-close the plan too — the
    # "13/13 DONE but still open" case from the screenshots.
    if status == "done":
        try:
            maybe_complete(row["project_id"])
        except Exception:
            pass
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
        "SELECT id, seq, text, status, note, action_json FROM plan_steps "
        "WHERE project_id=? ORDER BY seq", (p["id"],)).fetchall()
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
    # Deterministic first: if the step text itself is a known command, use it.
    try:
        from services.tool_registry import resolve_steps
        reg = resolve_steps(step_text)
        if reg:
            return {"kind": "actions", "actions": reg}
    except Exception:
        pass
    try:
        from services.deepseek_service import call_model
        raw = call_model(
            "You control a WINDOWS DESKTOP PC directly. Decide if this step is a "
            "desktop action you can DO now, or knowledge work.\n"
            "Desktop actions only — never phone/mobile, never website signup.\n"
            f"Project goal: {goal}\nStep: {step_text}\n\n"
            'If doable, reply ONLY with compact JSON (double quotes, commas between '
            'items): {"kind":"actions","actions":[{"action":"open_app","params":{"name_or_path":"notepad"}}]}\n'
            'Allowed actions: open_app, open_url, type_text, press, hotkey, screenshot, write_text.\n'
            'If knowledge work, reply ONLY: {"kind":"text"}', fast=True)
        d = _loads_lenient(raw)
        if d and d.get("kind") == "actions":
            actions = [a for a in d.get("actions", [])[:8]
                       if a.get("action") in _SAFE_ACTIONS]
            if actions:
                return {"kind": "actions", "actions": actions}
        return {"kind": "text"}
    except Exception as e:
        logger.warning(f"planner: step classification failed: {e}")
    return {"kind": "text"}


def _loads_lenient(raw: str):
    """Extract and parse the first JSON object from possibly-messy LLM output."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    blob = m.group()
    candidates = [blob]
    q = blob.replace("'", '"')                        # single -> double quotes
    candidates.append(q)
    candidates.append(re.sub(r",\s*([}\]])", r"\1", q))   # + strip trailing commas
    for attempt in candidates:
        try:
            return _json.loads(attempt)
        except Exception:
            continue
    return None


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
            # 1) concrete action stored at plan time (known command) — run as-is.
            # 2) else the step text itself may be a known command.
            # 3) else classify with the LLM. Deterministic first, generative last.
            stored = None
            if step.get("action_json"):
                try:
                    stored = _json.loads(step["action_json"])
                except Exception:
                    stored = None
            if not stored:
                try:
                    from services.tool_registry import resolve_steps
                    stored = resolve_steps(step["text"])
                except Exception:
                    stored = None
            plan = ({"kind": "actions", "actions": stored} if stored
                    else _step_to_actions(step["text"], proj["goal"] or proj["title"]))
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
        maybe_complete(pid)   # self-close if everything is done
        return {"ok": True, "done": done_ct, "blocked": blocked_ct}
    finally:
        with _exec_lock:
            _executing.discard(pid)


def maybe_complete(project_id: int) -> bool:
    """
    Completion watcher: if every step of an active project is done, mark the
    project 'done', emit a completion event, and return True. This is the fix
    for plans that showed 13/13 DONE yet never self-closed.
    """
    proj = get_project(project_id)
    if not proj or proj["status"] != "active" or not proj["steps"]:
        return False
    if all(s["status"] == "done" for s in proj["steps"]):
        with conn() as db:
            db.execute("UPDATE plan_projects SET status='done', updated_at=? WHERE id=?",
                       (_now(), project_id))
        _emit(f"✓ Project '{proj['title']}' complete — all {proj['total']} steps done. "
              f"Closing it out.", "success")
        try:   # let Pulse announce the win
            from services import pulse_service
            pulse_service._emit("plans", f"Project '{proj['title']}' finished — "
                                f"{proj['total']} steps done.", "success",
                                dedupe_key=f"plans:done:{proj['name']}")
        except Exception:
            pass
        try:   # reflect on the project + fire an event
            from services import reflection, event_bus
            reflection.reflect(f"project '{proj['title']}'",
                               [{"success": s["status"] == "done", "action": "step",
                                 "step": s["seq"]} for s in proj["steps"]],
                               True, kind="plan", workflow_name=proj["name"])
            event_bus.publish("plan.done", {"name": proj["name"]})
        except Exception:
            pass
        return True
    return False


# ── Watchdog: recover stalled steps, auto-close finished plans ────────────────

_watchdog_started = False
STALL_SECONDS = int(__import__("os").getenv("JARVIS_STEP_STALL", "180"))


def _watchdog_loop():
    import time
    time.sleep(45)
    while True:
        try:
            _watchdog_tick()
        except Exception as e:
            logger.warning(f"planner watchdog tick failed: {e}")
        time.sleep(60)


def _watchdog_tick():
    """
    For every active project: close it if finished; un-stick steps stuck in
    'doing' far too long (no executor running for it) by marking them blocked so
    the plan can be re-run or hand-edited instead of hanging forever.
    """
    for proj in list_projects():
        if proj["status"] != "active":
            continue
        if maybe_complete(proj["id"]):
            continue
        if is_executing(proj["id"]):
            continue   # actively running — leave its 'doing' steps alone
        now = datetime.now(timezone.utc)
        for s in proj["steps"]:
            if s["status"] != "doing":
                continue
            with conn() as db:
                row = db.execute("SELECT updated_at FROM plan_steps WHERE id=?",
                                 (s["id"],)).fetchone()
            try:
                age = (now - datetime.fromisoformat(row["updated_at"])).total_seconds()
            except Exception:
                age = 0
            if age > STALL_SECONDS:
                set_step_status(s["id"], "blocked",
                                note=(s.get("note") or "") + " [watchdog: stalled, "
                                      "marked blocked so the plan can continue]")
                _emit(f"Watchdog: step {s['seq']} of '{proj['title']}' stalled "
                      f"({int(age)}s) — marked blocked", "warning")


def start_watchdog():
    global _watchdog_started
    if _watchdog_started:
        return
    _watchdog_started = True
    _threading.Thread(target=_watchdog_loop, daemon=True, name="jarvis-plan-watchdog").start()
    logger.info("Planner watchdog started.")


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
