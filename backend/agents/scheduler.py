"""
agents/scheduler.py
AutoMode scheduling for Jarvis V8.5.
Wraps the EXISTING orchestrator pipeline with the `schedule` library so it can
run on an interval. No new pipeline logic — just periodic invocation of the
already-working run_pipeline().
"""
import threading
import time

try:
    import schedule as _schedule
except ImportError:
    _schedule = None

from agents.orchestrator import STATE

_thread: threading.Thread | None = None
_stop_evt = threading.Event()
_state = {"enabled": False, "every_minutes": 0, "config": None, "next_run": None}


def _runner():
    """Background loop that ticks the schedule library."""
    while not _stop_evt.is_set():
        if _schedule:
            _schedule.run_pending()
        time.sleep(1)


def start_schedule(config: dict, every_minutes: int = 60) -> dict:
    """Run the existing pipeline every `every_minutes`. Returns status dict."""
    global _thread
    if not _schedule:
        return {"enabled": False, "error": "schedule library not installed "
                "(pip install schedule)"}
    if every_minutes < 1:
        return {"enabled": False, "error": "every_minutes must be >= 1"}

    # Clear any existing job
    _schedule.clear("automode")

    def _job():
        # V9: scheduler drives the OrchestratorCore state machine, not the
        # legacy automation_engine pipeline.
        from agents.orchestrator_core import OrchestratorCore
        STATE.emit("scheduler", f"Scheduled run triggered (every {every_minutes}m)")
        goal = dict(config)
        goal.setdefault("goal_type", "freelance_application")
        goal.setdefault("auto_apply", False)   # scheduled runs default to safe (queue, don't auto-submit)
        core = OrchestratorCore()
        core.set_goal(goal)
        core.run()

    _schedule.every(every_minutes).minutes.do(_job).tag("automode")
    _state.update(enabled=True, every_minutes=every_minutes, config=config)

    # Start the ticking thread if not already running
    global _thread
    if _thread is None or not _thread.is_alive():
        _stop_evt.clear()
        _thread = threading.Thread(target=_runner, daemon=True)
        _thread.start()

    STATE.emit("scheduler", f"AutoMode scheduled every {every_minutes} minutes", "success")
    return get_schedule_status()


def stop_schedule() -> dict:
    """Cancel the scheduled pipeline."""
    if _schedule:
        _schedule.clear("automode")
    _state.update(enabled=False, every_minutes=0, next_run=None)
    STATE.emit("scheduler", "AutoMode schedule cleared")
    return get_schedule_status()


def get_schedule_status() -> dict:
    nxt = None
    if _schedule and _state["enabled"]:
        jobs = [j for j in _schedule.jobs if "automode" in j.tags]
        if jobs and jobs[0].next_run:
            nxt = jobs[0].next_run.isoformat()
    _state["next_run"] = nxt
    return dict(_state)
