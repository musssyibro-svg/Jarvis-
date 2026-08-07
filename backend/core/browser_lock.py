"""
core/browser_lock.py — single-owner browser access, via a HEARTBEAT LEASE.

The old version was a plain threading.Lock: if the owner thread died mid-bid, the
browser stayed locked forever and the income engine logged "browser busy" until a
restart. That's a real bug.

One audit proposed fixing it by force-releasing the lock after 5 minutes. We
deliberately do NOT do that: a slow-but-alive bid submission would have the
browser yanked out from under it, and two agents would then drive the same
Chrome instance — far worse than a stuck lock.

Instead the owner holds a LEASE it must renew (`heartbeat()`), which the executor
does naturally as it works. Ownership is only reclaimed when the heartbeat has
genuinely stopped — i.e. the owner is dead, not merely slow. Takeovers are
recorded so they show up in diagnostics instead of happening invisibly.
"""
import threading
import time
from datetime import datetime, timezone

# How long an owner may go silent before we consider it dead.
LEASE_SECONDS = 120
# Renew at least this often while working (executor calls heartbeat()).
HEARTBEAT_EVERY = 20

_state_lock = threading.Lock()
_owner = {"name": None, "since": None, "last_beat": 0.0, "thread_id": None}
_takeovers: list = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_expired() -> bool:
    if not _owner["name"]:
        return False
    return (time.time() - (_owner["last_beat"] or 0)) > LEASE_SECONDS


def acquire(owner: str, timeout: float = 0) -> dict:
    """
    Take browser ownership. Non-blocking by default; pass timeout to wait.
    Reclaims the lease only if the current owner has stopped heart-beating.
    """
    deadline = time.time() + max(0.0, timeout)
    while True:
        with _state_lock:
            current = _owner["name"]

            if current is None:
                _owner.update(name=owner, since=_now_iso(),
                              last_beat=time.time(),
                              thread_id=threading.current_thread().ident)
                return {"ok": True, "owner": owner}

            if current == owner:          # re-entrant for the same owner
                _owner["last_beat"] = time.time()
                return {"ok": True, "owner": owner, "reentrant": True}

            if _lease_expired():
                dead = current
                _takeovers.append({"from": dead, "to": owner, "at": _now_iso(),
                                   "silent_for_s": round(time.time() - _owner["last_beat"])})
                del _takeovers[:-20]
                _owner.update(name=owner, since=_now_iso(),
                              last_beat=time.time(),
                              thread_id=threading.current_thread().ident)
                return {"ok": True, "owner": owner, "took_over_from": dead,
                        "note": f"'{dead}' stopped responding for over "
                                f"{LEASE_SECONDS}s and its lease expired"}

            busy = {"ok": False, "busy_with": current, "since": _owner["since"],
                    "message": f"Browser busy (owned by {current})"}

        if time.time() >= deadline:
            return busy
        time.sleep(0.5)


def heartbeat(owner: str) -> bool:
    """Renew the lease. Long operations MUST call this to avoid being reclaimed."""
    with _state_lock:
        if _owner["name"] != owner:
            return False
        _owner["last_beat"] = time.time()
        return True


def release(owner: str) -> dict:
    with _state_lock:
        if _owner["name"] != owner:
            return {"ok": False, "message": f"{owner} does not hold the lock"}
        _owner.update(name=None, since=None, last_beat=0.0, thread_id=None)
    return {"ok": True}


def current_owner() -> dict:
    with _state_lock:
        return {"name": _owner["name"], "since": _owner["since"],
                "silent_for_s": (round(time.time() - _owner["last_beat"])
                                 if _owner["name"] else None),
                "lease_seconds": LEASE_SECONDS,
                "expired": _lease_expired(),
                "recent_takeovers": list(_takeovers[-5:])}


class browser_session:
    """
    `with browser_session('executor') as s:` — auto-renews the lease in the
    background so a slow-but-healthy job is never mistaken for a dead one.
    """
    def __init__(self, owner: str, timeout: float = 0):
        self.owner = owner
        self.timeout = timeout
        self.ok = False
        self.info = {}
        self._stop = threading.Event()

    def _beat(self):
        while not self._stop.wait(HEARTBEAT_EVERY):
            heartbeat(self.owner)

    def __enter__(self):
        self.info = acquire(self.owner, self.timeout)
        self.ok = self.info.get("ok", False)
        if self.ok:
            threading.Thread(target=self._beat, daemon=True,
                             name=f"lease-{self.owner}").start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self.ok:
            release(self.owner)
        return False
