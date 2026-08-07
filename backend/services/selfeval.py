"""
services/selfeval.py — grade the run, then change something.

reflection.py already writes a lesson after a task. A lesson nobody acts on is a
diary entry. This module does the part that has teeth:

    1. score confidence FROM EVIDENCE (verified steps, retries, durations) —
       never from a model's opinion of its own work,
    2. derive ONE concrete, measurable adjustment,
    3. APPLY it, by writing a tuning value that the executor actually reads.

The adjustments are deliberately narrow and numeric. "Be more careful next time"
changes nothing. "Wait 1.4s longer before typing into QQ, because 3 of the last 4
launches needed a retry and the successful ones took 4.2s" changes the next run,
and it can be checked afterwards.

Confidence is reported with its reasons attached. A bare "94%" is a number you
either believe or don't; "94% — every step verified, no retries, nothing timed
out" is a number you can argue with, which is the only kind worth showing.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from models.db import conn

KEY = "selfeval_log"
_MAX_LOG = 40
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── scoring ──────────────────────────────────────────────────────────────────

def score(steps: list[dict], ok: bool) -> dict:
    """
    Confidence in what just happened, from observations only.

    Starts at certainty and subtracts for every real doubt. A step that reported
    success but was never verified is the expensive case: it's the shape of "it
    told me it was done and it wasn't", so it costs more than an honest failure.
    """
    steps = steps or []
    if not steps:
        return {"confidence": 0, "reasons": ["nothing ran"], "evidence": []}

    total = len(steps)
    verified = sum(1 for s in steps if s.get("verified"))
    unverified_ok = sum(1 for s in steps
                        if s.get("success") and not s.get("verified")
                        and not s.get("skipped"))
    retried = [s for s in steps if (s.get("attempts") or 1) > 1]
    skipped = [s for s in steps if s.get("skipped")]
    slow = [s for s in steps if (s.get("duration_s") or 0) > 15]

    conf = 100
    reasons, evidence = [], []

    if not ok:
        conf -= 55
        broke = next((s for s in steps if not s.get("verified") and not s.get("skipped")),
                     None)
        reasons.append(f"it failed at step {broke.get('step')} "
                       f"({broke.get('action')})" if broke else "it failed")
    else:
        evidence.append(f"{verified}/{total} steps verified against the real screen")

    if unverified_ok:
        conf -= 20 * unverified_ok
        reasons.append(f"{unverified_ok} step(s) reported success without proof — "
                       f"I can't be sure those landed")
    if retried:
        conf -= 8 * len(retried)
        reasons.append(f"{len(retried)} step(s) needed a retry "
                       f"({', '.join(s.get('action', '?') for s in retried[:3])})")
    if slow:
        conf -= 5 * len(slow)
        reasons.append(f"{len(slow)} step(s) took over 15s")
    if skipped:
        reasons.append(f"{len(skipped)} step(s) you skipped — not counted against it")

    conf = max(0, min(100, conf))
    if ok and not reasons:
        reasons.append("every step verified, no retries, nothing slow")
    return {"confidence": conf, "reasons": reasons, "evidence": evidence,
            "verified": verified, "total": total,
            "retried": len(retried), "unverified": unverified_ok}


# ── adjustment ───────────────────────────────────────────────────────────────

def adjustment(steps: list[dict], ok: bool) -> dict | None:
    """
    The one thing to do differently, expressed as a number.

    Returns None when nothing measurable is wrong — inventing an adjustment for
    a clean run trains the system on noise, and a tuning file full of made-up
    corrections is worse than an empty one.
    """
    steps = steps or []

    # Retried launches that eventually worked -> the wait was too short.
    launch_retries = [s for s in steps
                      if s.get("action") in ("open_app", "wait_for_window")
                      and (s.get("attempts") or 1) > 1 and s.get("verified")]
    if launch_retries:
        s = launch_retries[0]
        app = (s.get("app") or s.get("name") or s.get("target") or "").strip()
        took = s.get("duration_s") or 0
        return {"kind": "wait_longer", "target": app or "this app",
                "delta_s": round(min(max(took * 0.4, 0.5), 4.0), 1),
                "why": f"{s.get('action')} needed {s.get('attempts')} attempts and "
                       f"took {took}s — it was ready, just not yet when I looked."}

    # Typing that failed verification -> focus wasn't settled.
    typing_fail = next((s for s in steps
                        if s.get("action") in ("type_text", "compose")
                        and not s.get("verified")), None)
    if typing_fail:
        return {"kind": "settle_before_typing", "target": "input",
                "delta_s": 0.4,
                "why": "text didn't land — the window took focus later than I assumed."}

    # Vision that ran long -> ask for less next time.
    slow_vision = next((s for s in steps
                        if s.get("action") == "analyze"
                        and (s.get("duration_s") or 0) > 45), None)
    if slow_vision:
        return {"kind": "shorter_vision", "target": "analyze",
                "delta_s": 0,
                "why": f"screen analysis took {slow_vision.get('duration_s')}s — "
                       f"cap the answer length on this machine."}

    if not ok:
        broke = next((s for s in steps if not s.get("verified")), None)
        if broke and (broke.get("failure") or {}).get("remedy"):
            return {"kind": "surface_remedy",
                    "target": broke.get("action", ""),
                    "delta_s": 0,
                    "why": broke["failure"]["remedy"]}
    return None


def apply(adj: dict) -> dict:
    """
    Make the adjustment real.

    wait_longer and settle_before_typing write into experience.py, which the
    executor already consults for per-app launch timing — so the change takes
    effect on the very next run rather than sitting in a log.
    """
    if not adj:
        return {"applied": False}
    kind = adj.get("kind")
    try:
        if kind == "wait_longer" and adj.get("target"):
            from services import experience
            # Recorded as a real observation of how long readiness took, which
            # is exactly what the launch-wait estimator learns from.
            experience.record(adj["target"], experience.WINDOW_READY, True,
                              float(adj.get("delta_s") or 1.0) + 2.0,
                              detail="self-evaluation: launch needed a retry")
            return {"applied": True, "where": "experience.launch_wait_for",
                    "effect": f"future launches of {adj['target']} wait longer"}
        if kind == "settle_before_typing":
            from services import config
            cur = float(config.get("type_settle_s", "0.3") or 0.3)
            new = round(min(cur + float(adj.get("delta_s") or 0.4), 2.0), 2)
            config.set("type_settle_s", str(new))
            return {"applied": True, "where": "config.type_settle_s",
                    "effect": f"pause before typing raised to {new}s"}
        if kind == "shorter_vision":
            from services import config
            cur = int(config.get("vision_max_tokens", "320") or 320)
            new = max(160, int(cur * 0.75))
            config.set("vision_max_tokens", str(new))
            return {"applied": True, "where": "config.vision_max_tokens",
                    "effect": f"screen analysis capped at {new} tokens"}
    except Exception as e:
        return {"applied": False, "error": str(e)[:200]}
    return {"applied": False, "note": "recorded, nothing to tune automatically"}


# ── the whole thing ──────────────────────────────────────────────────────────

def evaluate(goal: str, steps: list[dict], ok: bool,
             auto_apply: bool = True) -> dict:
    """
    Score, decide, apply, record. Called at the end of every chain.

    Never raises and never blocks: a failure to grade a run must not turn a
    successful run into a reported failure.
    """
    try:
        s = score(steps, ok)
        adj = adjustment(steps, ok)
        applied = apply(adj) if (adj and auto_apply) else {"applied": False}
        entry = {"at": _now(), "goal": (goal or "")[:200], "ok": bool(ok),
                 "confidence": s["confidence"], "reasons": s["reasons"],
                 "evidence": s["evidence"], "steps": s["total"],
                 "verified": s["verified"], "retried": s["retried"],
                 "next_time": adj, "applied": applied}
        _append(entry)
        try:
            from agents.orchestrator import STATE
            line = f"Confidence {s['confidence']}% — " + "; ".join(s["reasons"][:2])
            if applied.get("applied"):
                line += f". Next time: {applied['effect']}."
            STATE.emit("selfeval", line, "info" if s["confidence"] >= 70 else "warning")
        except Exception:
            pass
        return entry
    except Exception as e:
        return {"error": str(e)[:200], "confidence": None}


def _append(entry: dict) -> None:
    with _lock:
        log = recent(_MAX_LOG)
        log.append(entry)
        log = log[-_MAX_LOG:]
        try:
            with conn() as db:
                db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                           (KEY, json.dumps(log, ensure_ascii=False)))
        except Exception:
            pass


def recent(limit: int = 10) -> list[dict]:
    try:
        with conn() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (KEY,)).fetchone()
        if row and row["value"]:
            return json.loads(row["value"])[-limit:]
    except Exception:
        pass
    return []


def summary(limit: int = 10) -> dict:
    """For the UI: how confident has Jarvis been, and what has it changed?"""
    log = recent(limit)
    if not log:
        return {"runs": [], "average_confidence": None,
                "changes": [], "note": "no runs graded yet"}
    scored = [e["confidence"] for e in log if isinstance(e.get("confidence"), int)]
    changes = [{"at": e["at"], "effect": e["applied"]["effect"],
                "why": (e.get("next_time") or {}).get("why", "")}
               for e in log if (e.get("applied") or {}).get("applied")]
    return {"runs": list(reversed(log)),
            "average_confidence": round(sum(scored) / len(scored)) if scored else None,
            "changes": list(reversed(changes)),
            "note": "Confidence is computed from verified steps, retries and "
                    "timings — not from asking a model how it thinks it did."}
