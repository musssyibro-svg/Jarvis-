"""
services/brain_decision.py — the decision layer. It ADVISES; it never takes over.

The gap GPT identified: Jarvis had infrastructure (event bus, world model,
capability registry, model router) but nothing that decided *what to do next*.
The orchestrator just ran whatever it was handed.

This engine answers one question — "given everything I know right now, what
should happen with this goal?" — and returns a Decision the caller is free to
follow or ignore:

    EXECUTE   do it now
    QUEUE     valid, but something more important/urgent is running
    WAIT      a precondition isn't met (not logged in, no model, RAM critical)
    INTERRUPT this outranks what's running and should pre-empt it
    RECOVER   it's stuck/failing — change approach instead of retrying blindly
    LEARN     it finished; capture the lesson

Deliberately kept advisory so we don't end up with two controllers — the exact
mistake this project already made once. OrchestratorCore stays in charge.

It reasons over the REAL systems already present: world model (what's true),
capability registry (what I can do), model router (can I think well enough),
reflection/memory (what happened before).
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from services import event_bus


class Action:
    EXECUTE   = "execute"
    QUEUE     = "queue"
    WAIT      = "wait"
    INTERRUPT = "interrupt"
    RECOVER   = "recover"
    LEARN     = "learn"


@dataclass
class Decision:
    action: str
    reason: str
    confidence: float = 0.7
    priority: int = 5                      # 1 = highest
    blockers: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    capability: str | None = None
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# Goals that are worth interrupting for, roughly ordered.
URGENCY = {
    "user_command": 1,      # the human is waiting — always wins
    "recovery":     2,
    "deadline":     2,
    "freelance_application": 5,
    "background":   8,
    "maintenance":  9,
}

MAX_CONSECUTIVE_FAILURES = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Preconditions: things that make a goal impossible right now ───────────────

def _needs_llm(objective: str) -> bool:
    """
    Does this goal actually require a language model? Deterministic commands
    ("open notepad") are resolved by the tool registry with no LLM at all, so
    treating a missing model as a blocker for them would wrongly stop work that
    would have succeeded.
    """
    try:
        from services.tool_registry import resolve_steps
        if resolve_steps(objective or ""):
            return False        # a known command — no thinking required
    except Exception:
        pass
    return True


def _blockers_for(goal_type: str, objective: str, world: dict) -> list[str]:
    out = []
    sysd = world.get("system") or {}

    # Thinking capacity — only relevant if the goal actually needs to think.
    if _needs_llm(objective):
        try:
            from services import model_router
            pick = model_router.pick("planning" if goal_type != "chat" else "chat")
            if not pick.get("model"):
                out.append("no language model installed (ollama pull qwen2.5:3b)")
            # A too-small model is a caveat, not a blocker — it still produces
            # something, and stopping outright would be worse.
        except Exception:
            pass

    # Machine pressure: refusing beats thrashing.
    if sysd.get("ram", 0) >= 95:
        out.append(f"RAM at {sysd['ram']}% — running now would thrash the machine")

    # Freelance-specific preconditions.
    if goal_type == "freelance_application":
        logins = world.get("logins") or []
        try:
            from services import platform_meta
            biddable = [p for p in logins if platform_meta.kind(p) == "bid"]
        except Exception:
            biddable = logins
        if not biddable:
            out.append("not logged in to any bid platform — proposals can be drafted "
                       "but nothing can be submitted")
    return out


def _capability_for(objective: str) -> tuple[str | None, list[str]]:
    """Which capability should serve this goal, and what's missing for it?"""
    try:
        from services import capability_registry
        best = capability_registry.best_for(objective, top_k=1)
        if best:
            c = best[0]
            return c["name"], ([] if c.get("available") else c.get("missing", []))
    except Exception:
        pass
    return None, []


# ── The decision ──────────────────────────────────────────────────────────────

def decide(goal_type: str = "background", objective: str = "",
           world: dict | None = None, running: dict | None = None,
           history: dict | None = None) -> Decision:
    """
    Advise on a goal.
      world   : world_model snapshot (fetched if omitted)
      running : {"goal_type","objective","elapsed_s"} of the in-flight goal, if any
      history : {"consecutive_failures": int, "last_error": str} for this goal type
    """
    if world is None:
        try:
            from services import world_model
            world = world_model.get_cached()
        except Exception:
            world = {}
    history = history or {}
    priority = URGENCY.get(goal_type, 5)

    # 1. Stuck / repeatedly failing -> change approach, don't retry blindly.
    fails = int(history.get("consecutive_failures", 0))
    if fails >= MAX_CONSECUTIVE_FAILURES:
        d = Decision(
            action=Action.RECOVER, priority=URGENCY["recovery"], confidence=0.9,
            reason=f"failed {fails}x in a row"
                   + (f" ({history.get('last_error','')[:80]})" if history.get("last_error") else "")
                   + " — retrying the same way won't help",
            suggestions=["try a different capability or platform",
                         "check the blockers below before running again"])
        _publish(d, goal_type, objective)
        return d

    # 2. Hard preconditions.
    blockers = _blockers_for(goal_type, objective, world)
    cap, missing = _capability_for(objective) if objective else (None, [])
    if missing:
        blockers.append(f"'{cap}' needs: {', '.join(missing)}")
    if blockers:
        d = Decision(action=Action.WAIT, priority=priority, confidence=0.85,
                     reason="can't run properly yet", blockers=blockers,
                     capability=cap,
                     suggestions=["fix the blockers, or let Jarvis do the part it can"])
        _publish(d, goal_type, objective)
        return d

    # 3. Something already running — interrupt only if we clearly outrank it.
    if running and running.get("goal_type"):
        running_pri = URGENCY.get(running["goal_type"], 5)
        elapsed = float(running.get("elapsed_s", 0) or 0)
        if priority < running_pri:
            d = Decision(action=Action.INTERRUPT, priority=priority, confidence=0.8,
                         capability=cap,
                         reason=f"this is higher priority than the running "
                                f"'{running['goal_type']}' goal")
            _publish(d, goal_type, objective)
            return d
        if elapsed > 900:      # 15 min — something is likely wedged
            d = Decision(action=Action.INTERRUPT, priority=priority, confidence=0.6,
                         capability=cap,
                         reason=f"the running goal has been going {int(elapsed//60)}m "
                                f"and is probably stuck")
            _publish(d, goal_type, objective)
            return d
        d = Decision(action=Action.QUEUE, priority=priority, confidence=0.8,
                     capability=cap,
                     reason=f"'{running['goal_type']}' is running and outranks this")
        _publish(d, goal_type, objective)
        return d

    # 4. Clear to go.
    d = Decision(action=Action.EXECUTE, priority=priority, confidence=0.85,
                 capability=cap,
                 reason="preconditions met and nothing more important is running")
    _publish(d, goal_type, objective)
    return d


def after_goal(goal_type: str, objective: str, ok: bool, steps: list | None = None) -> Decision:
    """Called when a goal ends — decide whether there's a lesson worth keeping."""
    steps = steps or []
    retried = sum(1 for s in steps if (s.get("attempts") or 1) > 1)
    worth_learning = (not ok) or retried > 0
    d = Decision(
        action=Action.LEARN if worth_learning else Action.EXECUTE,
        priority=9, confidence=0.75,
        reason=("something went wrong or needed retries — worth remembering"
                if worth_learning else "clean run, nothing new to learn"))
    if worth_learning:
        try:
            from services import reflection
            reflection.reflect(f"{goal_type}: {objective}", steps, ok, kind=goal_type)
        except Exception:
            pass
    _publish(d, goal_type, objective)
    return d


def _publish(d: Decision, goal_type: str, objective: str) -> None:
    try:
        event_bus.publish("brain.decision", {
            "action": d.action, "goal_type": goal_type,
            "objective": (objective or "")[:80], "reason": d.reason,
            "priority": d.priority,
        })
    except Exception:
        pass


def explain(goal_type: str = "background", objective: str = "") -> dict:
    """Human-readable 'what would you do and why' — powers the console/API."""
    d = decide(goal_type, objective)
    return {"decision": d.to_dict(),
            "human": f"{d.action.upper()} — {d.reason}"
                     + (f" | blocked by: {'; '.join(d.blockers)}" if d.blockers else "")}
