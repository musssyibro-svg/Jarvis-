"""
core/browser_lock.py — single-owner browser lock (V9 Constraint 4).
Non-blocking: if a workflow already owns the browser, a second acquirer gets a
'browser busy' result IMMEDIATELY (no waiting, no deadlock during 24h runs).

Any code that drives Playwright (ExecutorAgent, bid_executor) must acquire()
before use and release() after. This makes OrchestratorCore-driven work and
queue execution mutually exclusive instead of silently racing the same context.
"""
import threading
from datetime import datetime, timezone

_lock  = threading.Lock()
_owner = {"name": None, "since": None}


def acquire(owner: str) -> dict:
    """Try to take browser ownership. Returns {ok, owner, busy_with?}."""
    got = _lock.acquire(blocking=False)
    if not got:
        return {"ok": False, "busy_with": _owner["name"],
                "since": _owner["since"],
                "message": f"Browser busy (owned by {_owner['name']})"}
    _owner["name"]  = owner
    _owner["since"] = datetime.now(timezone.utc).isoformat()
    return {"ok": True, "owner": owner}


def release(owner: str) -> dict:
    """Release ownership if held by `owner`. Idempotent/safe."""
    if _owner["name"] != owner:
        return {"ok": False, "message": f"{owner} does not hold the lock"}
    _owner["name"]  = None
    _owner["since"] = None
    try:
        _lock.release()
    except RuntimeError:
        pass
    return {"ok": True}


def current_owner() -> dict:
    return dict(_owner)


class browser_session:
    """Context manager: `with browser_session('executor') as s: if s.ok: ...`."""
    def __init__(self, owner: str):
        self.owner = owner
        self.ok    = False
        self.info  = {}
    def __enter__(self):
        self.info = acquire(self.owner)
        self.ok   = self.info.get("ok", False)
        return self
    def __exit__(self, *exc):
        if self.ok:
            release(self.owner)
        return False
