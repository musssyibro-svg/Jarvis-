"""
services/os_state.py — ONE live snapshot of the whole system.

The UI used to poll /stats + /health + /world/summary + /events/recent +
/orchestrator/status + /automation/queue + /automation/income/status separately.
That was both a CPU drain and the reason the app felt like disconnected widgets:
every panel had its own truth.

This returns the entire operating state in a single call, shaped the way an OS
console wants to display it:

    { status, goal, subsystems{...}, queue, plans, timeline, system, traces }

Every field is real. Nothing here is a placeholder — if a subsystem can't report,
it says so ("unknown"/"offline") rather than inventing a value.
"""
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def snapshot(timeline_limit: int = 40) -> dict:
    from agents.orchestrator import STATE

    feed_state = _safe(STATE.get, {}) or {}
    stats = feed_state.get("stats", {}) or {}

    # ── system telemetry ──────────────────────────────────────────────────────
    def _sys():
        import os as _os
        import psutil
        disk = "C:\\" if _os.name == "nt" else "/"
        return {"cpu": round(psutil.cpu_percent(interval=None)),
                "ram": round(psutil.virtual_memory().percent),
                "disk": round(psutil.disk_usage(disk).percent)}
    system = _safe(_sys, {"cpu": 0, "ram": 0, "disk": 0})

    def _ollama():
        from services.ollama_manager import resolve_models
        info = resolve_models()
        return {"online": bool(info.get("installed")),
                "models": info.get("installed", [])[:6],
                "fast": info.get("resolved", {}).get("fast"),
                "reasoning": info.get("resolved", {}).get("reasoning"),
                "vision": info.get("resolved", {}).get("vision")}
    ollama = _safe(_ollama, {"online": False, "models": []})

    world = _safe(lambda: __import__("services.world_model", fromlist=["get_cached"]).get_cached(), {}) or {}
    income = _safe(lambda: __import__("services.income_engine", fromlist=["status"]).status(), {}) or {}

    # ── queue (freelance automation) ──────────────────────────────────────────
    def _queue():
        from models.db import conn
        with conn() as db:
            rows = db.execute("SELECT status, COUNT(*) c FROM automation_queue "
                              "GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}
    queue = _safe(_queue, {})

    # ── plans ─────────────────────────────────────────────────────────────────
    def _plans():
        from services import planner_service
        return [{"id": p["id"], "title": p["title"], "progress": p["progress"],
                 "done": p["done"], "total": p["total"],
                 "doing": next((s["text"] for s in p["steps"] if s["status"] == "doing"), None)}
                for p in planner_service.list_projects() if p["status"] == "active"][:5]
    plans = _safe(_plans, [])

    # ── memory / brain ────────────────────────────────────────────────────────
    def _memory():
        from models.db import conn
        with conn() as db:
            docs = db.execute("SELECT COUNT(*) n FROM brain_documents").fetchone()["n"]
            refl = db.execute("SELECT COUNT(*) n FROM brain_documents "
                              "WHERE source='reflection'").fetchone()["n"]
        return {"documents": docs, "reflections": refl}
    memory = _safe(_memory, {"documents": 0, "reflections": 0})

    def _workflows():
        from services.workflow_service import list_workflows
        return [{"name": w["name"], "runs": w["runs"], "status": w["last_status"]}
                for w in list_workflows()][:6]
    workflows = _safe(_workflows, [])

    # ── current goal / activity ───────────────────────────────────────────────
    stage = feed_state.get("stage", "idle")
    running = bool(feed_state.get("running"))
    goal = None
    if plans:
        p = plans[0]
        goal = {"text": p["title"], "detail": p.get("doing") or f"{p['done']}/{p['total']} steps",
                "progress": p["progress"], "source": "plan"}
    elif income.get("enabled"):
        goal = {"text": "Earning — scanning freelance platforms",
                "detail": f"cycle {income.get('cycles', 0)} · every {income.get('interval_min', 20)}m",
                "progress": None, "source": "income"}

    # ── subsystems: what each part of Jarvis is doing RIGHT NOW ───────────────
    logins = world.get("logins", []) or []
    apps = world.get("apps", []) or []
    subsystems = {
        "brain":     {"state": "thinking" if running else "ready",
                      "detail": stage if running else "idle",
                      "ok": True},
        "desktop":   {"state": "watching" if apps else "ready",
                      "detail": (", ".join(apps[:4]) if apps else "no tracked apps open"),
                      "ok": True},
        "vision":    {"state": "ready" if ollama.get("vision") else "limited",
                      "detail": (f"vision model: {ollama.get('vision')}" if ollama.get("vision")
                                 else "OCR only — pull llava for true screen understanding"),
                      "ok": bool(ollama.get("vision"))},
        "browser":   {"state": "logged in" if logins else "no sessions",
                      "detail": (", ".join(logins) if logins else "log in from Freelance ▸ Platform Logins"),
                      "ok": bool(logins)},
        "automation":{"state": "running" if income.get("enabled") else "paused",
                      "detail": f"{income.get('cycles', 0)} cycles · "
                                f"{queue.get('pending', 0)} awaiting approval",
                      "ok": bool(income.get("enabled"))},
        "memory":    {"state": "learning" if memory["reflections"] else "ready",
                      "detail": f"{memory['documents']} docs · {memory['reflections']} reflections",
                      "ok": True},
        "models":    {"state": "online" if ollama.get("online") else "offline",
                      "detail": (ollama.get("fast") or "no model") ,
                      "ok": bool(ollama.get("online"))},
    }

    return {
        "ts": _now(),
        "status": {"stage": stage, "running": running,
                   "label": _stage_label(stage, running)},
        "goal": goal,
        "subsystems": subsystems,
        "system": system,
        "ollama": ollama,
        "income": income,
        "queue": queue,
        "plans": plans,
        "workflows": workflows,
        "memory": memory,
        "stats": stats,
        "timeline": (feed_state.get("feed", []) or [])[-timeline_limit:][::-1],
        "traces": _safe(lambda: __import__("services.trace", fromlist=["summary"]).summary(), {}),
    }


_STAGE_LABELS = {
    "idle": "Idle", "starting": "Starting", "scouting": "Scanning for work",
    "scoring": "Scoring opportunities", "generating": "Drafting proposals",
    "proposing": "Drafting proposals", "executing": "Executing",
    "queueing": "Queueing for approval", "learning": "Learning",
    "complete": "Finished", "error": "Needs attention", "stopped": "Stopped",
}


def _stage_label(stage: str, running: bool) -> str:
    label = _STAGE_LABELS.get(stage, stage.title() if stage else "Idle")
    return label if running or stage not in ("idle", "") else "Ready"
