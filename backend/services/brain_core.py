"""
services/brain_core.py — the coordinator that makes the parts feel like one mind.

Per GPT: the World Model isn't a peer service, it's the Brain's understanding of
reality. So brain_core OWNS the world model, the capability registry, memory, and
reflection, and presents them as one thing:

    Brain
      ├── World Model     (what's true right now)
      ├── Capabilities    (what I can do)
      ├── Memory / Brain  (what I know)
      ├── Reflection      (what I learned)
      └── Router          (which model / capability fits)

It also runs the EVENT-FIRST proactive loop: it subscribes to the event bus and,
on notable events (a job found, an app opened, RAM high, a login lost), decides
whether to surface a proactive nudge via Pulse — "act, and involve the user only
if needed", instead of waiting to be asked.
"""
import logging

from services import event_bus

logger = logging.getLogger("jarvis.brain")

_started = False


# ── Unified state ─────────────────────────────────────────────────────────────

def state() -> dict:
    """One snapshot of the whole mind — powers /brain/state and the Core UI."""
    from services import capability_registry, reflection, world_model
    world = world_model.get_cached()
    return {
        "world":        world,
        "world_summary": _safe(world_model.summary),
        "capabilities": len(capability_registry.all_capabilities()),
        "recent_events": event_bus.recent(limit=12),
        "reflections":  reflection.recent(limit=5),
    }


def route(goal: str) -> dict:
    """Which capability best solves this goal, and which model would run it."""
    from services import capability_registry, model_router
    caps = capability_registry.best_for(goal, top_k=3)
    cat = caps[0]["category"] if caps else "chat"
    task = {"planning": "planning", "vision": "vision"}.get(cat, "fast")
    return {"goal": goal, "capabilities": caps, "model": model_router.pick(task)}


def _safe(fn):
    try:
        return fn()
    except Exception:
        return ""


# ── Event-first proactive loop ────────────────────────────────────────────────

def _on_event(event: dict):
    """
    React to notable world events. Deliberately conservative: it NUDGES via Pulse
    (which already dedupes/cooldowns), it does not take irreversible action on its
    own. This is the "should I act? involve the user only if needed" gate.
    """
    et, data = event.get("type", ""), event.get("data", {})
    try:
        from services import pulse_service as pulse
    except Exception:
        return

    if et == "job.found":
        n = data.get("count", 1)
        pulse._emit("jobs", f"{n} new matching job(s) found — drafts are queued for "
                    f"your review.", "success", dedupe_key=f"brain:jobs:{n}")
    elif et == "login.changed" and data.get("state") == "logged_out":
        p = data.get("platform", "a platform")
        pulse._emit("system", f"Session for {p} dropped — bids there will pause until "
                    f"you log in again (Freelance ▸ Platform Logins).", "warning",
                    dedupe_key=f"brain:logout:{p}")
    elif et == "system.ram_high":
        pulse._emit("system", f"RAM is high ({data.get('ram')}%). I can unload the heavy "
                    f"model after tasks — close a few apps if it stays maxed.", "warning",
                    dedupe_key="brain:ram")
    elif et == "workflow.done" and not data.get("ok"):
        pulse._emit("plans", f"Your workflow '{data.get('name')}' hit a snag — I saved a "
                    f"reflection on where it broke (Core ▸ Skills).", "warning",
                    dedupe_key=f"brain:wf:{data.get('name')}")


def start():
    global _started
    if _started:
        return
    _started = True
    from services import world_model
    world_model.start()                     # begin sensing reality
    event_bus.subscribe("*", _on_event)     # begin reacting to it
    logger.info("Brain online (world model + event-first proactive loop).")
