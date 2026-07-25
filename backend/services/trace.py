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
"""
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

_local = threading.local()
_traces = deque(maxlen=60)
_lock = threading.Lock()


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
    """Record a hop in the current trace (no-op if nothing is tracing)."""
    t = getattr(_local, "current", None)
    if t is None:
        return
    try:
        t.steps.append({
            "component": component,
            "detail": str(detail)[:200],
            "ok": ok,
            "at_ms": int((time.time() - t.started) * 1000),
            **{k: str(v)[:120] for k, v in extra.items()},
        })
    except Exception:
        pass


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
