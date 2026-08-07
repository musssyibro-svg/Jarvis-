"""
services/narrate.py — "why did that happen?", answered as a chain.

The complaint this exists for: Jarvis says **Failed** and stops. One word, no
chain of custody, nothing to act on. What you want to see is the walk:

    Opened Edge                     ok      1.2s
    Searched "BMW M4"               ok      0.8s
    Waited for the page             ok      3.0s
    Looked at the screen            FAILED  62s     vision model timed out
      └ cause  : the vision model took longer than the 90s cap on CPU
      └ fix    : ollama pull llava:7b, or ask about a smaller region

Four sources are stitched together, and the ORDER matters — each is more
specific than the last, so the narrative gets more concrete as it goes:

    live_plan     what was supposed to happen, and how far it got
    trace         the code path the request actually took
    experience    what kind of failure this is, and its remedy
    environment   the machine fact that made it likely

Crucially this is ASSEMBLED, not generated. Asking a model to explain a failure
produces a fluent, plausible story that is right most of the time — and the
times it's wrong it is confidently wrong, which is worse than silence because
you'll act on it. Every line here comes from a recorded observation.
"""
from __future__ import annotations


def _plan_chain() -> list[dict]:
    try:
        from services import live_plan
        snap = live_plan.snapshot()
    except Exception:
        return []
    out = []
    for s in snap.get("steps", []):
        out.append({
            "text": s.get("text") or s.get("action", ""),
            "status": s.get("status"),
            "ms": s.get("ms"),
            "attempts": s.get("attempts", 0),
            "error": s.get("error", ""),
            "detail": s.get("detail", ""),
            "failure": s.get("failure") or {},
        })
    return out


def _trace_chain(limit: int = 12) -> list[dict]:
    try:
        from services import trace
        recent = trace.recent(1)
    except Exception:
        return []
    if not recent:
        return []
    t = recent[0]
    return [{"text": s.get("component", ""), "detail": s.get("detail", ""),
             "ok": s.get("ok")} for s in (t.get("steps") or [])[-limit:]]


def _machine_reason(kind: str) -> str:
    """
    The machine fact behind a failure class.

    This is the difference between "vision timed out" (annoying, mysterious) and
    "vision timed out — this PC has no usable GPU, so screen analysis runs on
    the CPU" (annoying, understood, and clearly not a bug to chase).
    """
    try:
        from services import environment
        cons = {c["key"]: c for c in environment.scan().get("constraints", [])}
    except Exception:
        return ""
    pick = {
        "ocr_timeout": "no_gpu",
        "no_model": "ollama_down",
        "network": "china_network",
        "focus_lost": "non_english_ui",
        "app_not_found": "non_english_ui",
        "browser_busy": "limited_ram",
    }.get(kind)
    c = cons.get(pick or "")
    return f"{c['fact']} {c['effect']}" if c else ""


def why(limit: int = 12) -> dict:
    """
    The full answer. Safe to call at any time — mid-run it explains what is
    happening now, after a run it explains how it ended.
    """
    plan = _plan_chain()
    trace_steps = _trace_chain(limit)

    try:
        from services import live_plan
        snap = live_plan.snapshot()
    except Exception:
        snap = {"status": "none"}

    broke = next((s for s in plan if s["status"] == "failed"), None)
    running = next((s for s in plan if s["status"] == "running"), None)

    # Prefer the executor's OWN classification, recorded at the moment of
    # failure. Re-deriving it here from the human-readable cause would quietly
    # disagree with the retry logic — and disagreeing with itself about why
    # something failed is exactly the behaviour this module exists to end.
    failure = (broke or {}).get("failure") or {}
    if broke and not failure and broke.get("error"):
        try:
            from services import experience
            failure = experience.classify(broke["error"])
        except Exception:
            failure = {}

    headline = _headline(snap, broke, running)
    machine = _machine_reason(failure.get("kind", ""))

    return {
        "headline": headline,
        "status": snap.get("status", "none"),
        "goal": snap.get("goal", ""),
        "chain": plan,
        "broke_at": broke,
        "running": running,
        "cause": failure.get("cause", ""),
        "fix": failure.get("remedy", ""),
        "kind": failure.get("kind", ""),
        "machine_reason": machine,
        "code_path": trace_steps,
        "confidence": _last_confidence(),
        "note": "Every line above is a recorded observation. Nothing here is a "
                "model's guess about its own behaviour.",
    }


def _headline(snap: dict, broke: dict | None, running: dict | None) -> str:
    status = snap.get("status", "none")
    if status == "none":
        return "Nothing has run yet."
    goal = snap.get("goal") or "the task"
    if running:
        return f"Working on \"{goal}\" — currently: {running['text']}."
    if status == "running":
        return f"Working on \"{goal}\" — between steps."
    if broke:
        return (f"\"{goal}\" stopped at step: {broke['text']}. "
                f"{broke.get('error') or 'No reason was recorded.'}")
    if status == "done":
        return (f"\"{goal}\" finished — {snap.get('done')}/{snap.get('total')} "
                f"steps verified.")
    return f"\"{goal}\": {status}."


def _last_confidence() -> dict | None:
    try:
        from services import selfeval
        log = selfeval.recent(1)
        if log:
            e = log[-1]
            return {"score": e.get("confidence"), "reasons": e.get("reasons", []),
                    "next_time": (e.get("applied") or {}).get("effect")}
    except Exception:
        pass
    return None


def as_text() -> str:
    """The same thing as a block of text, for chat replies and the report."""
    w = why()
    lines = [w["headline"], ""]
    for s in w["chain"]:
        mark = {"done": "ok", "failed": "FAILED", "running": "...",
                "skipped": "skipped", "pending": "-"}.get(s["status"], s["status"])
        ms = s.get("ms")
        timing = "" if not ms else (f"{ms}ms" if ms < 1000 else f"{ms / 1000:.1f}s")
        tries = f" ({s['attempts']} tries)" if (s.get("attempts") or 0) > 1 else ""
        lines.append(f"  {s['text']:<44} {mark:<8} {timing}{tries}")
        if s.get("error"):
            lines.append(f"      -> {s['error']}")
    if w["cause"]:
        lines += ["", f"Cause: {w['cause']}"]
    if w["machine_reason"]:
        lines.append(f"On this machine: {w['machine_reason']}")
    if w["fix"]:
        lines.append(f"Fix: {w['fix']}")
    c = w.get("confidence")
    if c and c.get("score") is not None:
        lines += ["", f"Confidence in the last run: {c['score']}% "
                      f"({'; '.join(c.get('reasons', [])[:2])})"]
        if c.get("next_time"):
            lines.append(f"Changed for next time: {c['next_time']}")
    return "\n".join(lines)
