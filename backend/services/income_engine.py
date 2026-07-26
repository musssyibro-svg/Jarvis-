"""
services/income_engine.py — the always-on freelance loop.

"Cycles: 0" in the screenshots is the whole problem: the pipeline only ran when
Ibrahim pressed a button, so it never actually earned in the background. This is
the missing continuous orchestration — Observe → Score → Draft → Queue, forever,
on its own clock:

    while enabled:
        scan logged-in + board platforms
        score & drop bad-fit / low-value jobs
        draft a tailored proposal for each good job
        queue it (auto-submit only if the user turned that on)
        log the cycle, sleep, repeat

State is persisted in `settings` (income_engine key) so it survives a restart
and resumes on boot. It reuses OrchestratorCore for the actual work — this module
just owns the clock, the cycle counter, and platform auto-selection.

Safe by default: it QUEUES proposals for review. It only auto-submits when the
freelance profile has auto_submit=True, and even then only on bid platforms the
user is logged into (see bid_executor's platform gate).
"""
import json
import threading
import time
from datetime import datetime, timezone

from models.db import conn

SETTINGS_KEY = "income_engine"

DEFAULTS = {
    # ON by default — the user's repeated ask is "scan on its own, always". Safe:
    # it only scans + drafts + queues; it never auto-submits unless the profile
    # opts in, and bid platforms are skipped unless logged in. Turn off anytime
    # from the Income Engine card (the choice persists).
    "enabled":      True,
    "interval_min": 20,          # minutes between cycles
    "platforms":    ["remoteok", "peopleperhour", "freelancer", "weworkremotely"],
    "max_jobs":     15,
    "cycles":       0,
    "last_run":     None,
    "last_result":  None,
}

_thread: threading.Thread | None = None
_lock = threading.Lock()
_wake = threading.Event()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(msg: str, level: str = "info"):
    try:
        from agents.orchestrator import STATE
        STATE.emit("income", msg, level)
    except Exception:
        pass


# ── Persisted config ──────────────────────────────────────────────────────────

def get_config() -> dict:
    try:
        with conn() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (SETTINGS_KEY,)).fetchone()
        if row and row["value"]:
            return {**DEFAULTS, **json.loads(row["value"])}
    except Exception:
        pass
    return dict(DEFAULTS)


def _save_config(cfg: dict):
    with conn() as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                   (SETTINGS_KEY, json.dumps(cfg)))


def status() -> dict:
    cfg = get_config()
    running = _thread is not None and _thread.is_alive()
    nxt = None
    if cfg["enabled"] and cfg.get("last_run"):
        try:
            last = datetime.fromisoformat(cfg["last_run"])
            nxt = (last.timestamp() + cfg["interval_min"] * 60)
            nxt = datetime.fromtimestamp(nxt, tz=timezone.utc).isoformat()
        except Exception:
            pass
    return {**cfg, "thread_alive": running, "next_run": nxt}


# ── Control ───────────────────────────────────────────────────────────────────

def start(interval_min: int | None = None, platforms: list | None = None,
          max_jobs: int | None = None) -> dict:
    cfg = get_config()
    cfg["enabled"] = True
    if interval_min is not None:
        cfg["interval_min"] = max(2, int(interval_min))
    if platforms is not None:
        cfg["platforms"] = platforms
    if max_jobs is not None:
        cfg["max_jobs"] = int(max_jobs)
    _save_config(cfg)
    _ensure_thread()
    _wake.set()   # run the first cycle promptly
    _emit(f"Income engine ON — scanning every {cfg['interval_min']} min across "
          f"{', '.join(cfg['platforms'])}.", "success")
    return status()


def stop() -> dict:
    cfg = get_config()
    cfg["enabled"] = False
    _save_config(cfg)
    _wake.set()
    _emit("Income engine paused.", "warning")
    return status()


def run_once_now() -> dict:
    """Trigger a cycle immediately without waiting for the interval."""
    _ensure_thread()
    _wake.set()
    return {"ok": True, "message": "Cycle triggered"}


# ── Engine loop ───────────────────────────────────────────────────────────────

def _ensure_thread():
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, daemon=True, name="jarvis-income")
            _thread.start()


def _active_platforms(cfg: dict) -> list[str]:
    """
    Scan the configured platforms, but for BID platforms only include ones the
    user is actually logged into — no point drafting bids we can't submit. Boards
    are always fine to scan (public).
    """
    from services import platform_meta
    try:
        from services import session_manager
        logged = set(session_manager.logged_in_platforms())
    except Exception:
        logged = set()
    out = []
    for p in cfg.get("platforms", []):
        if platform_meta.kind(p) == "bid":
            if p in logged:
                out.append(p)
        else:
            out.append(p)   # boards/talent/micro: scanning is always allowed
    return out or [p for p in cfg.get("platforms", []) if platform_meta.kind(p) != "bid"] \
        or ["remoteok"]


def _run_cycle(cfg: dict):
    from agents.v9_models import Goal
    from agents.orchestrator_core import OrchestratorCore
    from agents.orchestrator import STATE
    from services.profile_service import get_profile

    platforms = _active_platforms(cfg)
    profile = get_profile()
    _emit(f"Cycle starting — {', '.join(platforms)}")
    goal = Goal(
        goal_type="freelance_application",
        objective=f"Income engine sweep across {', '.join(platforms)}",
        constraints={"platforms": platforms,
                     "your_name": profile.get("name", ""),
                     "your_skills": profile.get("skills", ""),
                     "max_jobs": cfg.get("max_jobs", 15),
                     "min_score": profile.get("min_score", 30),
                     "auto_apply": False,
                     "auto_submit": bool(profile.get("auto_submit"))},
        approval_required=not profile.get("auto_submit"),
        success_condition={"min_applied": 0},
    )
    core = OrchestratorCore()
    core.set_goal(goal)
    snap = core.run_full_workflow()

    # A collision with another workflow is NOT a failed cycle — don't count it
    # and don't cry wolf in the feed. (This produced the misleading
    # "Cycle #3 done (FAILED)" lines.)
    if snap.get("skipped"):
        _emit("Another scan was already running — this tick was skipped.", "info")
        return

    cfg = get_config()
    cfg["cycles"] = int(cfg.get("cycles", 0)) + 1
    cfg["last_run"] = _now()
    ok = snap.get("state") == "COMPLETE"
    cfg["last_result"] = {"state": snap.get("state"), "error": snap.get("error")}
    _save_config(cfg)
    try:
        STATE.update_stats(cycles=cfg["cycles"])
    except Exception:
        pass
    _emit(f"Cycle #{cfg['cycles']} " + ("complete" if ok else
          f"finished with a problem: {snap.get('error') or snap.get('state')}") +
          f". Next in {cfg['interval_min']} min.", "success" if ok else "warning")


def _loop():
    # Small delay so startup finishes before the first sweep.
    _wake.wait(timeout=20)
    while True:
        cfg = get_config()
        if not cfg.get("enabled"):
            # Idle until re-enabled (or process exit).
            _wake.clear()
            _wake.wait(timeout=300)
            continue
        try:
            _run_cycle(cfg)
        except Exception as e:
            _emit(f"Cycle error: {e}", "error")
        # Sleep the interval, but wake early if start()/run_once_now() pokes us.
        cfg = get_config()
        _wake.clear()
        _wake.wait(timeout=max(120, cfg.get("interval_min", 20) * 60))


def start_watchdog():
    """Called at startup: resume the loop only if it was left enabled."""
    if get_config().get("enabled"):
        _ensure_thread()
