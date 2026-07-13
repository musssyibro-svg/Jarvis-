"""
backend/agents/commander.py
CommanderAgent: the single entry point for ALL Jarvis actions.

Flow:
  User/Chat → Commander → Planner → DesktopAgent / BrowserAgent / MemoryAgent
                        ↘ FreelanceAgent (jobs, proposals, etc.)

Commander routes by intent, coordinates multi-step plans,
emits to the live feed, and records outcomes to memory.
"""
import json
import threading
from datetime import datetime, timezone

from agents.orchestrator import STATE
from agents.memory_agent  import MemoryAgent

_running_task = threading.Event()
_task_lock    = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _emit(agent: str, msg: str, level: str = "info"):
    STATE.emit(agent, msg, level)


# ── Intent detection ──────────────────────────────────────────────────────────

INTENT_MAP = {
    "vision":  ["what's on", "whats on", "read screen", "read my screen", "on my screen",
                "see my screen", "look at my screen", "ocr", "find on screen",
                "detect on screen", "analyze screen", "analyse screen", "screen analysis"],
    "desktop": ["open ", "close ", "click", "type ", "press ", "move mouse",
                "take a screenshot", "screenshot", "window", "file", "folder", "notepad",
                "calculator", "run ", "launch ", "hotkey", "rename", "delete file", "move file"],
    "memory":  ["remember", "recall", "what did", "why did", "why do we",
                "why we", "decision", "history", "learn",
                "pattern", "forgot", "store this", "memorize"],
    "plan":    ["plan ", "how to", "steps to", "automate", "task list",
                "achieve", "do this for me"],
    "browser": ["browse", "navigate to", "go to website", "open url", "open http"],
    "freelance": ["job", "proposal", "bid", "freelancer", "hubstaff",
                  "scan jobs", "message", "reply", "analytics", "inbox"],
    "chat":    [],  # fallthrough — handled by AI directly
}


# FIX 3: exact confirmation phrases only (no substring matching, so "yesterday"
# or "approved proposals" never trigger a confirm).
CONFIRM_PHRASES = {"yes", "yes do it", "yes, do it", "confirm", "proceed", "approve"}

# FIX 5: pending risky actions awaiting confirmation, keyed by session.
_pending_actions: dict = {}


def detect_intent(message: str) -> str:
    m = message.lower().strip()
    # FIX 3: exact-phrase confirm detection BEFORE keyword scoring.
    if m in CONFIRM_PHRASES:
        return "confirm"
    # FIX 4: only the literal word "cancel" aborts a pending action.
    if m == "cancel":
        return "cancel"
    scores = {intent: 0 for intent in INTENT_MAP}
    for intent, keywords in INTENT_MAP.items():
        for kw in keywords:
            if kw in m:
                scores[intent] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "chat"


# ── Command execution ──────────────────────────────────────────────────────────

RISKY_ACTIONS = {"delete_file", "run_command", "close_app", "kill_app"}
RISKY_KEYWORDS = ["delete", "remove ", "rm ", "format", "uninstall", "kill ",
                  "shutdown", "restart pc", "wipe"]


def is_risky(message: str, action: str = "") -> bool:
    if action in RISKY_ACTIONS:
        return True
    m = message.lower()
    return any(kw in m for kw in RISKY_KEYWORDS)


def normalize_goal(message: str, session_id: str = "default"):
    """
    V9: Commander as smart adapter. Convert raw chat into a typed Goal object
    (agents.v9_models.Goal) for OrchestratorCore. Commander outputs Goal only —
    it never owns execution, orchestration, or approval state.
    """
    from agents.v9_models import Goal
    m = message.lower()
    auto_apply = any(k in m for k in ("apply", "submit", "bid"))
    goal_type = "freelance_application" if (auto_apply or "job" in m or "freelance" in m) else "chat"
    objective = message.strip()
    for marker in (" for ", " about ", " on "):
        if marker in m:
            objective = message.split(marker, 1)[1].strip()
            break
    import re as _re
    nums = _re.findall(r"\b(\d+)\b", m)
    max_jobs = int(nums[0]) if nums else 5
    return Goal(
        goal_type=goal_type,
        objective=objective,
        constraints={"platforms": ["remoteok", "weworkremotely", "hubstaff"],
                     "max_jobs": max_jobs, "auto_apply": auto_apply,
                     "session_id": session_id},
        approval_required=auto_apply,
        success_condition={"min_applied": 1 if auto_apply else 0},
    )


def get_status() -> dict:
    from agents.desktop_agent import get_status as ds
    from agents.vision_agent  import get_status as vs
    return {
        "commander":   "online",
        "desktop":     ds(),
        "vision":      vs(),
        "intent_map":  list(INTENT_MAP.keys()),
    }
