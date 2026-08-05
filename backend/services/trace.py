"""
services/trace.py — execution tracing. Every request records the EXACT path it took.

The recurring complaint was "I changed the code but the app feels identical" — and
the cause, twice now, was a request quietly taking a legacy path or dying in a
silent `except`. Tracing removes the guesswork: each request opens a trace, every
hop appends a step (with timing and outcome), and the whole path is visible at
/os/traces and in the UI's diagnostics panel.

    trace: chat "open notepad and type hello"
      ├─ commander.detect_intent        2ms   -> desktop
      ├─ tool_registry.resolve_steps    1ms   -> 3 steps
      ├─ desktop.execute_chain        842ms   -> open_app ok, focus ok, type ok
      └─ result                              -> verified done

Design: thread-local current trace so hops don't have to pass an id around;
bounded ring buffer; never raises; near-zero cost when nothing is tracing.

WHERE THE TIME WENT. Traces answer "what happened"; the cost table below
answers "what is slow", which is a different question and used to have no
answer at all. `timed()` wraps a hop, records its real duration, and feeds a
per-component rolling table — so "Jarvis feels sluggish" becomes a named
component with a p95, instead of a guess.

The table is deliberately separate from the trace ring buffer, because most
slow work happens with no trace open: the income engine, the proactive loop
and the watchdog all call models on background threads. Measuring only what
the chat box triggers would have profiled the fast half of the system.
"""
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

_local = threading.local()
_traces = deque(maxlen=60)
_lock = threading.Lock()

# component -> recent durations, ms. Bounded per component: this runs forever
# on a 16 GB machine, so it must not grow.
_COST_SAMPLES = 120
_costs: dict[str, deque] = {}
_costs_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Trace:
    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind                 # chat | workflow | plan | income | api
        self.label = label
        self.started = time.time()
        self.started_at = _now()
        self.steps: list[dict] = []
        self.result = None
        self.ok = None
        self.duration_ms = None
        # When the previous hop finished, so each step can carry its own real
        # cost instead of a running offset that has to be differenced later.
        self.last_ms = 0

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label,
                "started_at": self.started_at, "steps": self.steps,
                "result": self.result, "ok": self.ok,
                "duration_ms": self.duration_ms}


def start(kind: str, label: str) -> str:
    """Begin a trace on this thread. Returns its id."""
    try:
        t = _Trace(kind, label[:160])
        _local.current = t
        with _lock:
            _traces.append(t)
        return t.id
    except Exception:
        return ""


def step(component: str, detail: str = "", ok: bool | None = None, **extra) -> None:
    """
    Record a hop in the current trace (no-op if nothing is tracing).

    Called AFTER the hop's work, so `at_ms` is when it finished and `took_ms`
    is the gap since the previous hop finished. took_ms is computed here rather
    than differenced by whoever reads the trace, because that inference is only
    correct while every caller keeps recording after the work — and the first
    person to record one before it would produce a plausible, wrong profile.
    """
    t = getattr(_local, "current", None)
    if t is None:
        return
    try:
        at = int((time.time() - t.started) * 1000)
        # An explicit took_ms wins over the gap.
        #
        # The gap is only the step's cost when steps are recorded AS they
        # happen. A chain runs to completion and THEN records all its steps in
        # a loop, so the first one absorbed the entire run and the rest showed
        # 0ms. The 2026-08-05 report has it exactly: open_url [62406ms], wait
        # [0ms], analyze [0ms] — while the cost table, which measures the calls
        # themselves, said open_url 2.3s and analyze 55s. The trace was
        # pointing at the wrong step, which is worse than pointing nowhere.
        took = extra.pop("took_ms", None)
        t.steps.append({
            "component": component,
            "detail": str(detail)[:200],
            "ok": ok,
            "at_ms": at,
            "took_ms": int(took) if took is not None else max(0, at - t.last_ms),
            **{k: str(v)[:120] for k, v in extra.items()},
        })
        t.last_ms = at
    except Exception:
        pass


# ── Where the time went ──────────────────────────────────────────────────────

def record_cost(component: str, ms: float) -> None:
    """Add one measured duration to the rolling cost table."""
    try:
        with _costs_lock:
            d = _costs.get(component)
            if d is None:
                d = _costs[component] = deque(maxlen=_COST_SAMPLES)
            d.append(float(ms))
    except Exception:
        pass


class timed:
    """
    Time a hop and record it, whether or not a trace is open.

        with trace.timed("ollama.chat", model) as t:
            reply = client.chat(...)
            t.detail = f"{len(reply)} chars"

    An exception still records the cost and marks the hop failed, because a
    call that takes 40 seconds and then throws is exactly the kind of slowness
    worth seeing — dropping it would make the profile flattering and useless.
    """

    __slots__ = ("component", "detail", "_t0", "ok")

    def __init__(self, component: str, detail: str = ""):
        self.component = component
        self.detail = detail
        self.ok: bool | None = None
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = (time.time() - self._t0) * 1000.0
        record_cost(self.component, ms)
        ok = (False if exc_type is not None else
              (True if self.ok is None else self.ok))
        detail = self.detail
        if exc_type is not None:
            detail = f"{detail} — {exc_type.__name__}: {exc}".strip(" —")
        step(self.component, detail, ok=ok)
        return False        # never swallow


def _pct(values: list[float], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    i = min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))
    return int(ordered[i])


def profile(limit: int = 12) -> dict:
    """
    What is actually slow, worst first.

    Assembled from measurements, never from a model's opinion. Ranked by TOTAL
    time, not by the single worst call: a 30-second model call once an hour
    matters less than a 400 ms one on every keystroke, and ranking by max would
    put them the wrong way round.
    """
    with _costs_lock:
        snap = {k: list(v) for k, v in _costs.items()}
    rows = []
    for comp, vals in snap.items():
        if not vals:
            continue
        rows.append({
            "component": comp,
            "calls": len(vals),
            "total_ms": int(sum(vals)),
            "median_ms": _pct(vals, 0.50),
            "p95_ms": _pct(vals, 0.95),
            "max_ms": int(max(vals)),
        })
    rows.sort(key=lambda r: r["total_ms"], reverse=True)
    rows = rows[:limit]
    return {
        "components": rows,
        "slowest": rows[0]["component"] if rows else None,
        "note": ("Measured over the last "
                 f"{_COST_SAMPLES} calls of each component, this run only."),
    }


def reset_costs() -> None:
    with _costs_lock:
        _costs.clear()


# ── What actually went wrong ─────────────────────────────────────────────────
#
# Every failed action used to reduce to one line: {"success": False,
# "error": str(e)}. For a KeyError that is the string 'DISPLAY' and nothing
# else — no traceback, no arguments, no clue which of twenty actions raised it.
# The user's message became "it didn't work" and the only way forward was to
# reproduce it.
#
# These records are the second half of a failure. The user-facing message stays
# short and says the cause and the fix (see experience.KINDS); this is what a
# developer needs, kept next to it instead of in a log file nobody opens.

_FAILURES = 60
_failures = deque(maxlen=_FAILURES)

# Anything whose name looks like this never reaches a record. Jarvis drives a
# browser signed in to the user's accounts and can be asked to type a password;
# a diagnostics buffer that a screenshot could capture is not a place for that.
_SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                 "credential", "auth", "cookie", "session", "otp", "code",
                 "pin", "key")

# Whatever the user asked to be TYPED. Not a credential by its name — and that
# is exactly the problem, because "type my password" puts one here. Only the
# shape is kept: enough to tell "the text never arrived" from "the text arrived
# somewhere else", which is what these records are for.
_CONTENT_KEYS = ("text", "content", "value", "prompt", "query", "message")


def _safe_value(key: str, value) -> str:
    k = str(key).lower()
    if any(h in k for h in _SECRET_HINTS):
        return "[redacted]"
    s = str(value)
    if k in _CONTENT_KEYS:
        return f"[{len(s)} chars]"
    return s[:60] + ("…" if len(s) > 60 else "")


def failure(component: str, summary: str, detail: str = "", **context) -> dict:
    """
    Record a failed action in full: what failed, why, and the state around it.

    `detail` is for the traceback. Pass it — `str(e)` alone is what made this
    necessary. Returns the record so a caller can attach it to its own result.
    """
    rec = {
        "at": _now(),
        "trace": current_id(),
        "component": component,
        "summary": str(summary)[:300],
        "detail": str(detail)[-1500:],      # tail: the raise site, not the imports
        "context": {k: _safe_value(k, v) for k, v in (context or {}).items()},
    }
    try:
        _failures.append(rec)               # deque.append is atomic; no lock needed
    except Exception:
        pass
    return rec


def failures(limit: int = 20) -> list[dict]:
    """Recent failed actions, newest first."""
    return list(_failures)[-limit:][::-1]


def finish(result: str = "", ok: bool = True) -> None:
    """Close the current trace."""
    t = getattr(_local, "current", None)
    if t is None:
        return
    try:
        t.result = str(result)[:300]
        t.ok = ok
        t.duration_ms = int((time.time() - t.started) * 1000)
    finally:
        _local.current = None


def current_id() -> str | None:
    t = getattr(_local, "current", None)
    return t.id if t else None


def recent(limit: int = 20) -> list[dict]:
    with _lock:
        items = list(_traces)
    return [t.to_dict() for t in items[-limit:]][::-1]


def get(trace_id: str) -> dict | None:
    with _lock:
        for t in _traces:
            if t.id == trace_id:
                return t.to_dict()
    return None


def summary() -> dict:
    """Health at a glance: how many recent requests failed, and where."""
    items = recent(30)
    done = [t for t in items if t.get("ok") is not None]
    failed = [t for t in done if not t["ok"]]
    # which component most often reported a failure
    comp: dict[str, int] = {}
    for t in failed:
        for s in t["steps"]:
            if s.get("ok") is False:
                comp[s["component"]] = comp.get(s["component"], 0) + 1
    worst = max(comp.items(), key=lambda kv: kv[1])[0] if comp else None
    return {"recent": len(items), "completed": len(done), "failed": len(failed),
            "worst_component": worst}
