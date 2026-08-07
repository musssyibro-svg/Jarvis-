"""
services/event_bus.py — Jarvis's internal nervous system.

Until now modules called each other directly (commander -> executor -> desktop).
The Brain roadmap needs the opposite: modules PUBLISH what happened and anyone
interested SUBSCRIBES. That decoupling is what makes Jarvis event-first and
proactive — an "app.opened" or "job.found" event can wake the Brain to decide
whether to act, instead of everything waiting on a chat message.

Design:
  * publish(type, data) is non-blocking and never raises — a bad subscriber can
    never break the publisher.
  * subscribers are plain callables (fn(event)); wildcard "*" gets everything.
  * a ring buffer keeps the last N events for /events/recent and for the World
    Model's change feed.
  * it bridges to the existing SSE feed (agents.orchestrator.STATE) so published
    events still show up live in the UI with zero extra wiring.

Event types are namespaced strings: "app.opened", "app.closed", "login.changed",
"job.found", "workflow.done", "plan.done", "system.ram_high", "goal.complete", …
"""
import threading
import time
from collections import deque
from datetime import datetime, timezone

_subscribers: dict[str, list] = {}
_lock = threading.Lock()
_recent = deque(maxlen=300)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def subscribe(event_type: str, fn) -> None:
    """Register fn(event) for an event type, or '*' for all events."""
    with _lock:
        _subscribers.setdefault(event_type, []).append(fn)


def unsubscribe(event_type: str, fn) -> None:
    with _lock:
        if event_type in _subscribers and fn in _subscribers[event_type]:
            _subscribers[event_type].remove(fn)


def publish(event_type: str, data: dict | None = None,
            emit_feed: bool = False, level: str = "info") -> dict:
    """
    Publish an event. Fan-out happens AFTER releasing the lock so a slow
    subscriber can't block publishers. Returns the event dict.
    """
    event = {"type": event_type, "data": data or {}, "ts": _now(), "mono": time.time()}
    with _lock:
        _recent.append(event)
        targets = list(_subscribers.get(event_type, [])) + list(_subscribers.get("*", []))
    for fn in targets:
        try:
            fn(event)
        except Exception:
            pass  # never let a subscriber break the bus
    # Optional: surface on the live feed the user already watches.
    if emit_feed:
        try:
            from agents.orchestrator import STATE
            STATE.emit("event", f"{event_type}: {_short(data)}", level)
        except Exception:
            pass
    return event


def recent(limit: int = 50, prefix: str | None = None) -> list[dict]:
    with _lock:
        items = list(_recent)
    if prefix:
        items = [e for e in items if e["type"].startswith(prefix)]
    return [{k: v for k, v in e.items() if k != "mono"} for e in items[-limit:]][::-1]


def _short(data: dict | None) -> str:
    if not data:
        return ""
    bits = []
    for k, v in list(data.items())[:3]:
        bits.append(f"{k}={str(v)[:40]}")
    return ", ".join(bits)
