"""
services/live_plan.py — the plan, visible while it runs.

Jarvis executed. It did not think out loud. You typed a command, watched a
spinner, and found out what happened when it was over — and if it went wrong,
"Failed" was the whole story.

This holds ONE live plan: the ordered steps, which one is running right now,
which are done, which broke and why. It is written as the work happens, so the
UI can show the plan and the activity on the same screen instead of making you
switch between a planner that shows intentions and a feed that shows events.

It also carries the controls that only make sense against a visible plan:

    skip(i)     don't do this step, carry on
    retry(i)    do that step again
    stop()      finish the current step, then stop

All three are COOPERATIVE. They set a flag that the executor reads between
steps; nothing is ever killed mid-action. Interrupting a keystroke sequence
halfway leaves half a sentence in your document, and interrupting a bid
submission leaves a half-filled form on a real freelance site.

Deliberately in-memory and single-plan: this is a live view of what is happening
now, not a history. History is trace.py, which persists.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

_lock = threading.RLock()
_plan: dict | None = None

PENDING, RUNNING, DONE, FAILED, SKIPPED = (
    "pending", "running", "done", "failed", "skipped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(msg: str, level: str = "info"):
    try:
        from agents.orchestrator import STATE
        STATE.emit("planner", msg, level)
    except Exception:
        pass


def begin(goal: str, steps: list[dict], lines: list[str] | None = None,
          source: str = "") -> dict:
    """
    Publish a new plan. Replaces whatever was there — one plan at a time,
    because two live plans competing for the same keyboard is not a feature.
    """
    global _plan
    lines = lines or []
    with _lock:
        _plan = {
            "id": uuid.uuid4().hex[:12],
            "goal": goal,
            "source": source,
            "status": RUNNING,
            "started_at": _now(),
            "started_ms": int(time.time() * 1000),
            "ended_at": None,
            "current": -1,
            "error": None,
            "steps": [{
                "i": i,
                "text": (lines[i] if i < len(lines) else
                         _describe(s)),
                "action": (s or {}).get("action", ""),
                "params": _safe_params((s or {}).get("params", {})),
                "status": PENDING,
                "attempts": 0,
                "started_at": None,
                "ended_at": None,
                "ms": None,
                "detail": "",
                "error": "",
                "failure": None,
            } for i, s in enumerate(steps or [])],
            "controls": {"skip": set(), "retry": None, "stop": False},
        }
        snap = _public(_plan)
    _emit(f"Plan: {len(snap['steps'])} steps — " +
          " → ".join(s["text"] for s in snap["steps"][:6]) +
          (" …" if len(snap["steps"]) > 6 else ""))
    _publish("plan.started", snap)
    return snap


def ensure(goal: str, steps: list[dict], source: str = "") -> bool:
    """
    Publish a plan only if one isn't already live.

    The executor calls this so that a chain started from anywhere — chat, a
    saved workflow, the income engine — still shows up on the planner screen.
    A caller that already published a richer plan (with its own wording) keeps
    it; being shown the same plan twice in two vocabularies is worse than once.
    """
    with _lock:
        if _plan and _plan["status"] == RUNNING:
            return False
    begin(goal, steps, source=source)
    return True


def _describe(step: dict) -> str:
    try:
        from services.decompose import describe
        return describe(step)
    except Exception:
        return (step or {}).get("action", "step").replace("_", " ")


def _safe_params(params: dict) -> dict:
    """Params for display. Long text is clipped; nothing secret is stored here."""
    out = {}
    for k, v in (params or {}).items():
        s = str(v)
        out[k] = s if len(s) <= 120 else s[:119] + "…"
    return out


def step_start(i: int, note: str = "") -> None:
    with _lock:
        if not _plan or i >= len(_plan["steps"]):
            return
        s = _plan["steps"][i]
        s.update(status=RUNNING, started_at=_now(), detail=note)
        s["attempts"] += 1
        _plan["current"] = i
        snap = _public(_plan)
    _publish("plan.step", snap)


def step_end(i: int, ok: bool, detail: str = "", error: str = "",
             failure: dict | None = None) -> None:
    """
    Close a step.

    `failure` is the executor's own classification. It is stored rather than
    re-derived later, because re-classifying a human-readable cause string
    ("Windows couldn't find that application") against patterns written for raw
    errors loses the diagnosis — and then the explanation screen says "I don't
    know why" about a failure the executor understood perfectly well.
    """
    with _lock:
        if not _plan or i >= len(_plan["steps"]):
            return
        s = _plan["steps"][i]
        started = s.get("started_at")
        s.update(status=DONE if ok else FAILED, ended_at=_now(),
                 detail=detail or s.get("detail", ""), error=error or "",
                 failure=failure or s.get("failure"))
        if started:
            try:
                t0 = datetime.fromisoformat(started)
                s["ms"] = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
            except Exception:
                pass
        snap = _public(_plan)
    if not ok:
        _emit(f"Step {i + 1} failed: {error or 'no reason given'}", "error")
    _publish("plan.step", snap)


def finish(ok: bool, error: str = "") -> dict:
    with _lock:
        if not _plan:
            return {}
        _plan["status"] = DONE if ok else FAILED
        _plan["ended_at"] = _now()
        _plan["error"] = error or None
        for s in _plan["steps"]:
            if s["status"] in (PENDING, RUNNING):
                s["status"] = SKIPPED if ok else PENDING
        _plan["current"] = -1
        snap = _public(_plan)
    _publish("plan.finished", snap)
    return snap


# ── controls ─────────────────────────────────────────────────────────────────

def skip(i: int) -> dict:
    """Mark a step to be skipped. Takes effect before that step starts."""
    with _lock:
        if not _plan or i >= len(_plan["steps"]):
            return {"ok": False, "error": "no such step"}
        st = _plan["steps"][i]["status"]
        if st in (DONE, FAILED, SKIPPED):
            return {"ok": False, "error": f"step {i + 1} already {st}"}
        if st == RUNNING:
            return {"ok": False,
                    "error": f"step {i + 1} is running — it will finish first. "
                             f"Use stop if you want everything to halt."}
        _plan["controls"]["skip"].add(i)
        _plan["steps"][i]["detail"] = "you skipped this"
    _emit(f"Step {i + 1} will be skipped.", "warning")
    return {"ok": True, "skipped": i}


def retry(i: int) -> dict:
    """Ask for a finished step to run again once the current one ends."""
    with _lock:
        if not _plan or i >= len(_plan["steps"]):
            return {"ok": False, "error": "no such step"}
        _plan["controls"]["retry"] = i
    _emit(f"Will retry step {i + 1}.", "warning")
    return {"ok": True, "retry": i}


def stop(reason: str = "") -> dict:
    """Stop after the current step. Delegates the real halt to control.py."""
    with _lock:
        if _plan:
            _plan["controls"]["stop"] = True
    try:
        from services import control
        return control.cancel(reason or "you stopped the plan")
    except Exception as e:
        return {"ok": False, "error": str(e)}


def should_skip(i: int) -> bool:
    with _lock:
        return bool(_plan and i in _plan["controls"]["skip"])


def take_retry() -> int | None:
    """Consume a pending retry request, if any."""
    with _lock:
        if not _plan:
            return None
        i, _plan["controls"]["retry"] = _plan["controls"]["retry"], None
        return i


# ── reading ──────────────────────────────────────────────────────────────────

def _public(p: dict) -> dict:
    steps = [dict(s) for s in p["steps"]]
    done = sum(1 for s in steps if s["status"] == DONE)
    total = len(steps) or 1
    return {
        "id": p["id"], "goal": p["goal"], "source": p.get("source", ""),
        "status": p["status"], "started_at": p["started_at"],
        "ended_at": p["ended_at"], "error": p["error"],
        "current": p["current"], "steps": steps,
        "done": done, "total": len(steps),
        "progress": int(done * 100 / total),
        "elapsed_ms": int(time.time() * 1000) - p["started_ms"],
        "controls": {"skip": sorted(p["controls"]["skip"]),
                     "retry": p["controls"]["retry"],
                     "stop": p["controls"]["stop"]},
    }


def snapshot() -> dict:
    with _lock:
        return _public(_plan) if _plan else {"status": "none", "steps": [],
                                             "total": 0, "done": 0,
                                             "progress": 0, "current": -1}


def current_step() -> dict | None:
    with _lock:
        if not _plan or _plan["current"] < 0:
            return None
        return dict(_plan["steps"][_plan["current"]])


def clear() -> None:
    global _plan
    with _lock:
        _plan = None


def _publish(topic: str, payload: dict) -> None:
    try:
        from services import event_bus
        event_bus.publish(topic, {"id": payload.get("id"),
                                  "status": payload.get("status"),
                                  "current": payload.get("current"),
                                  "progress": payload.get("progress")})
    except Exception:
        pass
