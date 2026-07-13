"""
adapters/commander_adapter.py — V9 chat adapter (extracted per Hard Constraint 1).

handle_message in commander.py was too tightly coupled to legacy execution
(execute_command / create_plan), so the chat entry point is extracted here.

Flow (mandatory):  /chat -> CommanderAdapter -> OrchestratorCore -> ExecutorAgent

The adapter does ONLY:
  - intent detection (reuses commander.detect_intent — pure, no execution)
  - goal normalization (reuses commander.normalize_goal — pure, returns Goal)
  - memory retrieval
  - SSE emission of visible, chat-facing events (UX guardrail A)
  - inline approval prompts (UX guardrail B)

It performs ZERO direct desktop/browser execution. All actions go through the
ExecutorAgent, which OrchestratorCore owns. Approval lifecycle lives in the
ExecutorAgent, never here.
"""
from agents.orchestrator import STATE
from agents.v9_models import Goal, Action


def _emit(agent: str, msg: str, level: str = "info"):
    """Visible chat-facing SSE event (UX guardrail A)."""
    STATE.emit(agent, msg, level)


def _memory_context(message: str) -> dict:
    """Read-side memory retrieval (best-effort; never blocks chat)."""
    try:
        from agents.memory_agent import MemoryAgent
        return {"win_patterns": MemoryAgent.get_win_patterns(limit=3)}
    except Exception:
        return {}


def handle_chat(message: str, session_id: str = "default") -> dict:
    """
    Single chat entry point. Returns:
      {response, intent, needs_approval, data}
    Never executes desktop/browser directly.
    """
    if not message or not message.strip():
        return {"response": "Say something and I'll get to work.", "intent": "chat"}

    from agents.commander import detect_intent  # pure intent detection only
    intent = detect_intent(message)
    _emit("commander", f"Message received -> intent: {intent}")

    # ── Confirm / cancel: delegate to ExecutorAgent's approval lifecycle ────────
    if intent == "confirm":
        from agents.executor_agent import ExecutorAgent
        ex = _shared_executor()
        if not ex.has_pending(session_id):
            return {"response": "No pending action to confirm.", "intent": "chat"}
        _emit("executor", "Approval granted -> executing", "warning")
        result = ex.confirm(session_id)
        ok = result.get("status") == "complete"
        msg = "Done ✓" if ok else f"Could not complete: {result.get('result')}"
        if ok and result.get("note"):
            msg = f"Done ✓ ({result['note']})"
        return {"response": msg, "intent": "executor", "data": result}

    if intent == "cancel":
        ex = _shared_executor()
        result = ex.cancel(session_id)
        return {"response": result.get("message", "Cancelled."), "intent": "chat"}

    # ── Desktop / browser actions: route to ExecutorAgent (no direct execution) ─
    if intent in ("desktop", "browser"):
        return _route_action(message, session_id, intent)

    # ── Goal-driven work (freelance application etc.): OrchestratorCore ─────────
    if intent in ("plan", "freelance"):
        from agents.orchestrator_core import OrchestratorCore
        from agents.commander import normalize_goal
        goal = normalize_goal(message, session_id)
        _emit("orchestrator", f"Starting goal: {goal.objective}", "info")
        core = OrchestratorCore()
        core.set_goal(goal)
        # Run in background so chat stays responsive; feed shows progress.
        import threading
        threading.Thread(target=core.run_full_workflow, daemon=True).start()
        return {"response": f"On it — working toward: {goal.objective}. "
                            f"Watch the live feed for progress.",
                "intent": "orchestrator", "data": {"goal_id": goal.goal_id}}

    # ── Vision: perception only ────────────────────────────────────────────────
    if intent == "vision":
        from agents.perception_agent import perception
        state = perception.observe(message)
        return {"response": state.get("screen_text", "") or "I couldn't read the screen.",
                "intent": "vision", "data": state}

    # ── Memory: the Brain (V10) — save and recall personal knowledge ───────────
    if intent == "memory":
        return _handle_memory(message)

    # ── Plain chat (V10: grounded in the Brain when it has something relevant) ─
    from services.deepseek_service import call_model
    knowledge = _brain_context(message)
    if knowledge:
        _emit("brain", "Found relevant knowledge in your brain", "info")
        prompt = (f"Relevant knowledge from the user's personal brain "
                  f"(saved by them — treat as trusted context):\n{knowledge}\n\n"
                  f"User message: {message}")
        reply = call_model(prompt, fast=True)
        if reply.startswith("[No AI available"):
            # No LLM installed — the brain itself is still useful: answer with
            # the retrieved knowledge instead of a dead error.
            reply = ("(No AI model installed — showing what your brain knows.)\n\n"
                     + knowledge)
        return {"response": reply, "intent": "chat", "data": {"brain_used": True}}
    reply = call_model(message, fast=True)
    return {"response": reply, "intent": "chat"}


# ── Brain helpers (V10) ───────────────────────────────────────────────────────

_REMEMBER_RE = None

def _handle_memory(message: str) -> dict:
    """'remember <x>' saves to the brain; anything else searches it."""
    import re
    m = re.match(r"^\s*(?:remember|memorize|store this|save this)[:,]?\s*(?:that\s+)?(.*)",
                 message, re.IGNORECASE | re.DOTALL)
    try:
        from services import brain_service as brain
        if m and m.group(1).strip():
            fact = m.group(1).strip()
            r = brain.ingest(fact[:60], fact, source="chat")
            _emit("brain", "Saved to your brain", "success")
            return {"response": f"Remembered ✓ — \"{fact[:120]}\"",
                    "intent": "memory", "data": r}
        # recall path: search the brain, answer with the LLM over the hits
        hits = brain.search(message, k=3)
        results = hits.get("results", [])
        if not results:
            return {"response": "Nothing in my brain matches that yet. "
                                "Say 'remember ...' or feed me files in the Brain panel.",
                    "intent": "memory"}
        knowledge = "\n\n".join(f"[{h['title']}]\n{h['text'][:600]}" for h in results)
        from services.deepseek_service import call_model
        reply = call_model(
            f"Answer the user's question using ONLY this saved knowledge:\n"
            f"{knowledge}\n\nQuestion: {message}", fast=True)
        if reply.startswith("[No AI available"):
            reply = "Here's what your brain has on that:\n\n" + knowledge
        return {"response": reply, "intent": "memory",
                "data": {"mode": hits.get("mode"), "matches": len(results)}}
    except Exception as e:
        return {"response": f"Brain error: {e}", "intent": "memory"}


def _brain_context(message: str) -> str:
    """Best-effort brain retrieval for plain chat; never blocks or raises."""
    try:
        from services import brain_service as brain
        return brain.context_for(message, k=3)
    except Exception:
        return ""


# ── Action routing through ExecutorAgent ──────────────────────────────────────
import threading
_EXECUTOR = None
_executor_lock = threading.Lock()

def _shared_executor():
    """One ExecutorAgent instance so pending-approval state persists across turns."""
    global _EXECUTOR
    if _EXECUTOR is None:
        with _executor_lock:
            if _EXECUTOR is None:
                from agents.executor_agent import ExecutorAgent
                _EXECUTOR = ExecutorAgent()
    return _EXECUTOR


def _route_action(message: str, session_id: str, intent: str) -> dict:
    """
    Turn a desktop/browser chat command into an ExecutorAgent action.
    Emits visible SSE (guardrail A). Risky actions return inline approval
    prompt (guardrail B). NO direct desktop/browser calls here.
    """
    ex = _shared_executor()
    m = message.lower()

    # Map common phrasings to a typed Action; ExecutorAgent decides risk + acts.
    action = None
    if "screenshot" in m or "screen shot" in m:
        action = Action(action_type="screenshot", params={}, risk_level="low")
        _emit("executor", "Taking a screenshot", "info")
    elif "open " in m:
        app = message.lower().split("open ", 1)[1].strip().split()[0]
        action = Action(action_type="open_app", params={"name_or_path": app}, risk_level="low")
        _emit("executor", f"Opening {app}", "info")
    elif "close " in m:
        app = message.lower().split("close ", 1)[1].strip().split()[0]
        action = Action(action_type="close_app", params={"process_name": app}, risk_level="high")
        _emit("executor", f"Closing {app}", "info")
    elif intent == "browser" or "navigate" in m or "go to" in m:
        url = ""
        for tok in message.split():
            if tok.startswith("http"):
                url = tok; break
        action = Action(action_type="browse", params={"url": url}, risk_level="low")
        _emit("browser", f"Navigating to {url or 'page'}", "info")
    else:
        # Let the executor's own decision logic parse a generic command.
        action = Action(action_type="parse", params={"text": message}, risk_level="medium")
        _emit("executor", "Working on your request", "info")

    # Risky → inline approval prompt in chat (guardrail B), owned by ExecutorAgent
    if ex.is_risky(action.action_type) or action.risk_level == "high":
        ex.request_approval(session_id, action)
        _emit("executor", f"[Approval Required] {action.action_type}?", "warning")
        return {"response": f"This action may be destructive: {action.action_type}. "
                            f"Reply 'yes' to confirm or 'cancel' to abort.",
                "intent": intent, "needs_approval": True}

    result = ex.execute_action(action)
    ok = result.get("success", False)
    label = action.params.get("name_or_path") or action.action_type
    _emit("executor", f"{action.action_type} -> {'ok' if ok else 'failed'}",
          "success" if ok else "error")
    return {"response": (f"Done: {label} ✓" if ok
                         else f"Couldn't do {label}: {result.get('error','')}"),
            "intent": intent, "data": result}
