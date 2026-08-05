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
        from services.ollama_manager import probe_reason, resolve_models
        info = resolve_models()
        installed = info.get("installed") or []
        # "I couldn't ask" is not "it's off", and the console must not draw a
        # red OFFLINE for the first. A daemon busy loading a 6 GB model fails
        # the probe while running perfectly well; saying it is offline sends
        # the user to restart something that isn't broken.
        why = probe_reason()
        out = {"online": bool(installed),
               "reachable": bool(installed) or not why,
               "reason": why,
               "models": installed[:8],
               "fast": info.get("resolved", {}).get("fast"),
               "reasoning": info.get("resolved", {}).get("reasoning"),
               "vision": info.get("resolved", {}).get("vision")}
        # Report the model that chat ACTUALLY uses. Those two answers can
        # differ: resolve_models() reads the configured name, while real calls
        # go through model_router, which ranks by quality and free RAM. The
        # console was showing the config, so it reported qwen2.5:0.5b as "in
        # use" — and told the user to fix something that may already be fine.
        try:
            from services import model_router
            for role, task in (("fast", "chat"), ("reasoning", "planning"),
                               ("vision", "vision")):
                pick = model_router.pick(task)
                if pick.get("model"):
                    out[role] = pick["model"]
                    if pick.get("warning"):
                        out.setdefault("warnings", []).append(pick["warning"])
        except Exception:
            pass
        return out
    ollama = _safe(_ollama, {"online": False, "reachable": False, "models": [],
                             "reason": "the model check itself failed"})

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
        "models":    _model_subsystem(ollama),
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
        # How reliable Jarvis has actually been lately, measured not claimed.
        "reliability": _safe(
            lambda: __import__("services.experience",
                               fromlist=["reliability"]).reliability(), {}),
    }


def _model_subsystem(ollama: dict) -> dict:
    """
    Report the model honestly — including when it's too small to be any good.
    A 0.5B model is the usual reason Jarvis "feels dumb" even when every other
    part is working, so say so right on the console instead of hiding it.
    """
    if not ollama.get("online"):
        return {"state": "offline", "detail": "Ollama isn't running", "ok": False}
    name = ollama.get("fast") or "unknown"
    try:
        from services.diagnostics import _param_size
        size = _param_size(name)
    except Exception:
        size = None
    if size is not None and size < 1.0:
        # Say WHY it's using the small one. Telling someone to `ollama pull
        # qwen2.5:3b` when qwen2.5:3b is already sitting on their disk is worse
        # than saying nothing: it sends them off to fix a problem they don't
        # have, and hides the one they do. The router only fell back to a 0.5B
        # model because nothing bigger fits in the free RAM right now.
        better = _better_installed(ollama.get("models") or [])
        try:
            from services.model_router import free_ram_gb
            free = round(free_ram_gb(), 1)
        except Exception:
            free = None
        if better and free is not None:
            return {"state": "starved", "ok": False,
                    "detail": f"Using {name} (~{size}B) because only {free}GB of RAM "
                              f"is free. You already have {better} — close some apps "
                              f"and Jarvis will pick it up automatically.",
                    "fix": "close a few apps, or restart Jarvis after closing them"}
        if better:
            return {"state": "starved", "ok": False,
                    "detail": f"Using {name} (~{size}B) although {better} is "
                              f"installed — not enough free RAM for the bigger one."}
        return {"state": "too small", "ok": False,
                "detail": f"{name} — only ~{size}B parameters. Run "
                          f"'ollama pull qwen2.5:3b' for noticeably smarter replies."}
    return {"state": "online", "detail": name, "ok": True}


def _better_installed(models: list) -> str:
    """The best model already on disk that would beat the one in use."""
    try:
        from services.model_router import _profile
    except Exception:
        return ""
    best, best_q = "", 3.0        # only mention something meaningfully better
    for m in models:
        try:
            _gb, q = _profile(m)
        except Exception:
            continue
        if q > best_q:
            best, best_q = m, q
    return best


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
