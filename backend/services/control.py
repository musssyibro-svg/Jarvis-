"""
services/control.py — the stop button for autonomous work.

Jarvis could start things and could be told to start more things, but there was
no way to say "wait" or "stop" once it was going. On a system meant to run
unattended for hours that's the difference between an assistant and a runaway
process: the only way to interrupt a 20-minute freelance sweep was to kill the
backend, which loses the queue and every learned timing since the last write.

Two levels, deliberately:

    PAUSE   finish the action in flight, then hold before the next one.
    CANCEL  same, but abandon the goal entirely.

Neither one kills anything mid-action. Yanking control away halfway through a
bid submission leaves a half-filled form on a real freelance site, and halfway
through typing leaves half a sentence in the user's document. So this is
COOPERATIVE: long-running loops call checkpoint() between steps, and that is
where the interruption lands. The cost is that a pause can take as long as the
current step; the benefit is that Jarvis is never interrupted into an
inconsistent state.

Also here: explain(), which answers "why are you doing this?" from the execution
trace rather than by asking a model to speculate about its own behaviour.
"""
import threading
from datetime import datetime, timezone

RUNNING, PAUSING, PAUSED, CANCELLING = "running", "pausing", "paused", "cancelling"

_lock = threading.Lock()
_pause = threading.Event()      # set = a pause has been requested
_cancel = threading.Event()     # set = abandon the current goal
_resumed = threading.Event()    # signalled to wake a paused worker
_resumed.set()

_state = {"mode": RUNNING, "since": None, "reason": "", "paused_at_step": None}

# How many chains are inside run_scope() right now.
#
# This exists to answer one question: is a cancel flag still MEANT for
# something, or is it left over? Cancel is deliberately global — one Stop
# button must halt whatever is running, whether that's a chat command or the
# income engine — but "global" made it outlive the thing it was aimed at.
_active = 0


def _now():
    return datetime.now(timezone.utc).isoformat()


def _emit(msg: str, level: str = "info"):
    try:
        from agents.orchestrator import STATE
        STATE.emit("control", msg, level)
    except Exception:
        pass


class Cancelled(Exception):
    """Raised by checkpoint() when the current goal has been cancelled."""


# ── Commands ─────────────────────────────────────────────────────────────────

def pause(reason: str = "") -> dict:
    """Ask work to hold at the next safe point."""
    with _lock:
        if _cancel.is_set():
            return {"ok": False, "mode": CANCELLING,
                    "message": "A cancel is already in progress."}
        if _pause.is_set():
            return {"ok": True, "mode": _state["mode"], "message": "Already pausing."}
        _pause.set()
        _resumed.clear()
        _state.update(mode=PAUSING, since=_now(), reason=reason or "you asked")
    _emit("Pausing — finishing the current step first, then holding.", "warning")
    return {"ok": True, "mode": PAUSING,
            "message": "Pausing. The step in flight will finish first — "
                       "Jarvis is never interrupted mid-action."}


def resume() -> dict:
    with _lock:
        was = _state["mode"]
        _pause.clear()
        _resumed.set()
        _state.update(mode=RUNNING, since=_now(), reason="", paused_at_step=None)
    if was in (PAUSED, PAUSING):
        _emit("Resumed.", "success")
    return {"ok": True, "mode": RUNNING, "message": "Resumed."}


def cancel(reason: str = "") -> dict:
    """Abandon the current goal at the next safe point."""
    with _lock:
        _cancel.set()
        _pause.clear()
        _resumed.set()          # never leave a paused worker stuck on a cancel
        _state.update(mode=CANCELLING, since=_now(), reason=reason or "you asked")
    _emit("Cancelling — stopping after the current step.", "warning")
    return {"ok": True, "mode": CANCELLING,
            "message": "Cancelling. The current step finishes, then Jarvis stops."}


def clear() -> dict:
    """Reset to running. Called when a goal ends, so the next one starts clean."""
    with _lock:
        _pause.clear()
        _cancel.clear()
        _resumed.set()
        _state.update(mode=RUNNING, since=None, reason="", paused_at_step=None)
    return {"ok": True, "mode": RUNNING}


class run_scope:
    """
    Marks a chain as running, so a leftover cancel can be told apart from a
    live one. Use as a context manager around any checkpoint-guarded loop.
    """

    def __enter__(self):
        global _active
        with _lock:
            _active += 1
        return self

    def __exit__(self, *exc):
        global _active
        with _lock:
            _active = max(0, _active - 1)
        return False


def busy() -> bool:
    with _lock:
        return _active > 0


def clear_stale() -> dict:
    """
    Drop a cancel flag that nothing is running to receive.

    THE BUG THIS FIXES, straight out of a real runtime report:

        10:58:39 [control] Cancelling — stopping after the current step.
        10:58:43 check my qq messages   -> Cancelled, 0ms
        10:58:49 check my qq messages   -> Cancelled, 0ms
        11:00:22 open calculator        -> Cancelled, 0ms
        11:01:02 open calculator        -> Cancelled, 0ms
        11:01:24 open calculator        -> Cancelled, 0ms

    One press of Stop, and every command after it died instantly — for the rest
    of the session, until the backend was restarted. From the outside Jarvis
    simply stopped working and gave no usable reason: five different commands,
    five identical one-line failures. The orchestrator cleared the flag when a
    GOAL finished, but a chat command never goes through the orchestrator, so
    nothing ever cleared it.

    A cancel with nothing running is by definition stale: whatever it was aimed
    at is already over. Clearing it is safe. Clearing it while work IS running
    would silently un-cancel that work, so this refuses to.
    """
    with _lock:
        if _active > 0:
            return {"ok": False, "cleared": False, "reason": "work is still running"}
        was = _cancel.is_set() or _pause.is_set()
    if not was:
        return {"ok": True, "cleared": False}
    clear()
    _emit("Cleared a leftover stop from an earlier command — this one will run.",
          "info")
    return {"ok": True, "cleared": True}


# ── The bit worker loops call ────────────────────────────────────────────────

def checkpoint(step: str = "", block: bool = True) -> None:
    """
    Call this BETWEEN steps, never inside one.

    Returns immediately when nothing is pending. Blocks here while paused, and
    raises Cancelled if the goal has been abandoned — so a caller that doesn't
    catch it unwinds cleanly instead of carrying on regardless.
    """
    if _cancel.is_set():
        raise Cancelled(_state.get("reason") or "cancelled")

    if _pause.is_set():
        with _lock:
            _state.update(mode=PAUSED, paused_at_step=step or None)
        _emit(f"Paused{f' before: {step}' if step else ''}. "
              f"Press Resume when you're ready.", "warning")
        if not block:
            return
        # Wake every second so a cancel arriving during a pause is noticed
        # promptly rather than waiting for a resume that never comes.
        while not _resumed.wait(1.0):
            if _cancel.is_set():
                raise Cancelled(_state.get("reason") or "cancelled")
        if _cancel.is_set():
            raise Cancelled(_state.get("reason") or "cancelled")


def is_paused() -> bool:
    return _state["mode"] in (PAUSING, PAUSED)


def is_cancelled() -> bool:
    return _cancel.is_set()


def status() -> dict:
    with _lock:
        s = dict(_state)
    s["can_pause"] = s["mode"] == RUNNING
    s["can_resume"] = s["mode"] in (PAUSED, PAUSING)
    return s


# ── "Why are you doing this?" ────────────────────────────────────────────────

def explain(limit: int = 6) -> dict:
    """
    Answer "why are you doing this?" from what actually happened.

    Built from the execution trace and the live goal, NOT by asking a model to
    narrate its own behaviour — a model asked to explain itself will produce a
    plausible story whether or not it matches what the code did, which is worse
    than no explanation because it's convincing.
    """
    out = {"at": _now(), "goal": None, "doing": None, "because": [],
           "steps": [], "control": status()}

    try:
        from services.os_state import snapshot
        snap = snapshot(timeline_limit=1)
        goal = snap.get("goal") or {}
        out["goal"] = goal.get("text")
        out["doing"] = (snap.get("status") or {}).get("label")
        if goal.get("source") == "income":
            out["because"].append(
                "You turned on autonomous earning, so Jarvis scans freelance "
                "sites on a timer and drafts proposals for anything that fits.")
        sub = snap.get("subsystems") or {}
        for name, s in sub.items():
            if s.get("state") in ("running", "scanning", "watching") and s.get("detail"):
                out["because"].append(f"{name}: {s['detail']}")
    except Exception as e:
        out["because"].append(f"(couldn't read live state: {str(e)[:80]})")

    try:
        from services import trace
        for t in trace.recent(limit):
            steps = t.get("steps") or []
            out["steps"].append({
                "request": t.get("label") or t.get("name"),
                "ok": t.get("ok"),
                "ms": t.get("ms"),
                "path": [{"component": s.get("component"),
                          "detail": s.get("detail"),
                          "ok": s.get("ok")} for s in steps[-6:]],
            })
    except Exception:
        pass

    if not out["because"]:
        out["because"].append("Nothing is running — Jarvis is waiting for you.")
    return out
