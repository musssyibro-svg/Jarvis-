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

    # ── Long-term project planner (V10): "plan project X to ..." / "new project X"
    #    Checked BEFORE keyword-based desktop routing: the explicit "plan
    #    project" phrasing is unambiguous, and a goal like "...launch the store"
    #    would otherwise be misread as a desktop 'launch' command.
    planned = _maybe_plan_project(message)
    if planned is not None:
        return planned

    # ── Desktop / browser actions: route to ExecutorAgent (no direct execution) ─
    if intent in ("desktop", "browser"):
        # Questions are lookups, never commands: "why did we stop using
        # browser-use?" must not launch a browser just because it contains
        # a keyword. Question-shaped messages go to the brain instead.
        if _is_question(message):
            return _handle_memory(message)
        return _route_action(message, session_id, intent)

    # ── Goal-driven work ─────────────────────────────────────────────────────────
    # Non-freelance goals ("build me a website", "plan how to pass thermodynamics")
    # become a TRACKED project with auto-decomposed steps — Jarvis OS behavior —
    # instead of a one-off chat reply. Freelance goals keep the orchestrator.
    if intent == "plan" and not any(
            k in message.lower() for k in ("job", "proposal", "bid", "freelanc", "apply")):
        return _plan_goal(message)
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

    # ── Plain chat (V10: grounded in the Brain when it has something relevant;
    #    V10.2: personal facts are ALWAYS in context so Jarvis knows the user) ─
    from services.deepseek_service import call_model
    knowledge = _brain_context(message)
    profile = _profile()
    if knowledge or profile:
        if knowledge:
            _emit("brain", "Found relevant knowledge in your brain", "info")
        parts = []
        if profile:
            parts.append(f"Facts about the user:\n{profile}")
        if knowledge:
            parts.append(f"Relevant knowledge from the user's personal brain "
                         f"(saved by them — treat as trusted context):\n{knowledge}")
        prompt = "\n\n".join(parts) + f"\n\nUser message: {message}"
        reply = call_model(prompt, fast=True)
        if reply.startswith("[No AI available"):
            # No LLM installed — the brain itself is still useful: answer with
            # the retrieved knowledge instead of a dead error.
            reply = ("(No AI model installed — showing what your brain knows.)\n\n"
                     + (knowledge or profile))
        return {"response": reply, "intent": "chat",
                "data": {"brain_used": bool(knowledge)}}
    reply = call_model(message, fast=True)
    return {"response": reply, "intent": "chat"}


# ── Brain helpers (V10) ───────────────────────────────────────────────────────

_REMEMBER_RE = None

def _handle_memory(message: str) -> dict:
    """
    'remember <x>'                  -> personal fact (always in Jarvis's context)
    'remember decision: <x>'        -> a WHY, kept for future context
    'remember for <project>: <x>'   -> scoped to a project workspace
    anything else                   -> searches the brain
    """
    import re
    m = re.match(r"^\s*(?:remember|memorize|store this|save this)[:,]?\s*(?:that\s+)?(.*)",
                 message, re.IGNORECASE | re.DOTALL)
    try:
        from services import brain_service as brain
        if m and m.group(1).strip():
            fact = m.group(1).strip()
            source, project = "fact", None
            dm = re.match(r"^decision[:,]\s*(.*)", fact, re.IGNORECASE | re.DOTALL)
            pm = re.match(r"^for\s+([\w-]+)[:,]\s*(.*)", fact, re.IGNORECASE | re.DOTALL)
            if dm and dm.group(1).strip():
                source, fact = "decision", dm.group(1).strip()
            elif pm and pm.group(2).strip():
                project, fact = pm.group(1), pm.group(2).strip()
            r = brain.ingest(fact[:60], fact, source=source, project=project)
            _emit("brain", f"Saved {source}" + (f" to {project}" if project else ""), "success")
            label = {"decision": "Decision recorded", "fact": "Remembered"}[source]
            return {"response": f"{label} ✓ — \"{fact[:120]}\""
                                + (f" [{project}]" if project else ""),
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


def _profile() -> str:
    """Personal facts, always injected (bounded); never blocks or raises."""
    try:
        from services import brain_service as brain
        return brain.profile_context()
    except Exception:
        return ""


def _maybe_plan_project(message: str):
    """
    Detect explicit long-term-planning phrasing and create a tracked project
    with auto-decomposed steps. Returns a response dict, or None if this isn't
    a planning request (so normal routing continues).

      'plan project mistore: launch the store'
      'new project ev to research battery thermal PINNs'
      'start a project jarvis for the assistant build'

    Requires the literal word 'project' so it never hijacks the freelance
    orchestrator's 'plan how to ...' phrasing.
    """
    import re
    m = re.match(
        r"^\s*(?:plan|new|start|track|create)\s+(?:a\s+)?project\s+"
        r"(?:called\s+|named\s+|my\s+)?([\w-]+)\s*(?:[:—-]|\bto\b|\bfor\b)?\s*(.*)$",
        message, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    name = (m.group(1) or "").strip()
    goal = (m.group(2) or "").strip()
    if not name or name.lower() in ("the", "a", "an", "my", "to", "for", "called", "named"):
        return None
    try:
        from services import planner_service as planner
        r = planner.create_project(name, goal or message, title=name)
        proj = planner.get_project(r["project_id"])
        steps = "\n".join(f"  {i+1}. {s['text']}" for i, s in enumerate(proj["steps"]))
        _emit("planner", f"Project '{name}' planned ({proj['total']} steps)", "success")
        return {"response": f"Planned **{name}** — {proj['total']} steps:\n{steps}\n\n"
                            f"Track it in the Plans panel; say 'remember for {name}: ...' "
                            f"to attach notes and decisions.",
                "intent": "planner", "data": {"project_id": r["project_id"]}}
    except Exception as e:
        return {"response": f"Couldn't create the plan: {e}", "intent": "planner"}


_GOAL_STOPWORDS = {"plan", "how", "to", "steps", "step", "a", "an", "the", "me",
                   "my", "for", "build", "create", "make", "set", "up", "please",
                   "jarvis", "can", "you", "i", "want", "need", "help", "with",
                   "do", "this", "automate", "achieve", "and", "of"}

def _plan_goal(message: str) -> dict:
    """
    Turn a goal-shaped message into a tracked project (auto-named), so 'build
    me a website' produces a real plan with steps in the Plans panel — the
    Planner runs without the user having to know the 'plan project X' syntax.
    """
    import re
    words = [w for w in re.findall(r"[\w-]+", message.lower())
             if w not in _GOAL_STOPWORDS]
    name = "-".join(words[:2]) if words else f"goal-{__import__('time').strftime('%m%d%H%M')}"
    try:
        from services import planner_service as planner
        r = planner.create_project(name, message, title=name)
        proj = planner.get_project(r["project_id"])
        steps = "\n".join(f"  {i+1}. {s['text']}" for i, s in enumerate(proj["steps"]))
        _emit("planner", f"Goal planned as project '{name}' ({proj['total']} steps)", "success")
        return {"response": f"I've planned **{name}** — {proj['total']} steps:\n{steps}\n\n"
                            f"It's tracked in the Plans panel. Say 'remember for {name}: ...' "
                            f"to attach notes; I'll nudge you about progress.",
                "intent": "planner", "data": {"project_id": r["project_id"]}}
    except Exception as e:
        return {"response": f"Couldn't create the plan: {e}", "intent": "planner"}


_QUESTION_STARTS = ("why ", "what ", "what's", "whats ", "when ", "where ",
                    "who ", "how ", "did ", "tell me", "explain")

def _is_question(message: str) -> bool:
    """
    Information-seeking phrasings that must never execute an action, even when
    they contain action keywords. Deliberately excludes 'can you...' /
    'could you...' — those are polite commands, not questions.
    """
    return message.lower().strip().startswith(_QUESTION_STARTS)


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


# Verb grammar: match any tense/form ("open", "opening", "launch", "start up"),
# and capture the target up to a connective ("and", "then", ",") or a follow-up
# verb ("type", "press", "write"). This is what makes "Opening notepad type
# hello" work instead of dying with "could not interpret command".
import re as _re

_STOP = r"(?=\s+(?:and|then|,)\b|\s+(?:type|write|press|hit)\b|[.!?]|$)"
_OPEN_RE  = _re.compile(
    r"\b(?:open(?:ing|s)?|launch(?:ing|es)?|start(?:ing|s)?(?:\s+up)?|run(?:ning)?)\s+"
    r"(?:the\s+|my\s+|up\s+|app\s+)?([\w][\w .+&-]*?)" + _STOP, _re.IGNORECASE)
_CLOSE_RE = _re.compile(
    r"\b(?:clos(?:e|ing|es)|quit(?:ting|s)?|kill(?:ing|s)?|exit(?:ing|s)?|"
    r"terminat(?:e|ing|es)|stop(?:ping|s)?)\s+"
    r"(?:the\s+|my\s+|app\s+)?([\w][\w .+&-]*?)" + _STOP, _re.IGNORECASE)
_TYPE_RE  = _re.compile(
    r"\b(?:type|write)\s+(?:the\s+(?:text|words?)\s+)?[\"'“]?(.+?)[\"'”]?\s*$",
    _re.IGNORECASE)
_PRESS_RE = _re.compile(r"\b(?:press|hit)\s+(?:the\s+)?([\w]+(?:\s*\+\s*[\w]+)*)\s*(?:key)?\s*$",
                        _re.IGNORECASE)


def _parse_command_steps(message: str) -> list:
    """
    Parse a natural desktop command into an ordered list of typed Actions.
    Handles compound phrasings: "open notepad and type hello then press enter".
    Returns [] when nothing matched (caller falls back to the LLM parser).
    """
    steps = []
    m = message.strip()
    low = m.lower()

    if "screenshot" in low or "screen shot" in low or "capture the screen" in low:
        return [Action(action_type="screenshot", params={}, risk_level="low")]

    om = _OPEN_RE.search(m)
    if om:
        app = om.group(1).strip().rstrip(".!?,")
        if app:
            steps.append(Action(action_type="open_app",
                                params={"name_or_path": app}, risk_level="low"))
    cm = _CLOSE_RE.search(m)
    if cm and not om:  # "open X" phrases can contain 'stop'/'exit' words in the app name
        app = cm.group(1).strip().rstrip(".!?,")
        if app:
            steps.append(Action(action_type="close_app",
                                params={"process_name": app}, risk_level="high"))
    tm = _TYPE_RE.search(m)
    if tm:
        text = tm.group(1).strip()
        # don't re-type the pressed key ("type hello and press enter")
        text = _re.sub(r"\s*(?:and\s+|then\s+|,\s*)?(?:press|hit)\s+\w+\s*$", "", text,
                       flags=_re.IGNORECASE).strip()
        if text:
            steps.append(Action(action_type="type_text",
                                params={"text": text}, risk_level="low"))
    pm = _PRESS_RE.search(m)
    if pm:
        keys = [k.strip().lower() for k in pm.group(1).split("+") if k.strip()]
        if len(keys) > 1:
            steps.append(Action(action_type="hotkey", params={"keys": keys}, risk_level="low"))
        elif keys:
            steps.append(Action(action_type="press", params={"key": keys[0]}, risk_level="low"))
    return steps


def _llm_parse_steps(message: str) -> list:
    """
    Last-resort parser: ask the fast local model to translate the command into
    typed steps. Returns [] if no LLM or the output isn't usable.
    """
    try:
        from services.deepseek_service import call_model
        import json as _json
        raw = call_model(
            "Translate this desktop command into JSON steps. Allowed actions:\n"
            '  open_app {"name_or_path": "..."} | close_app {"process_name": "..."}\n'
            '  type_text {"text": "..."} | press {"key": "..."} | hotkey {"keys": [...]}\n'
            '  screenshot {} | browse {"url": "..."}\n'
            'Reply ONLY with: {"steps":[{"action":"...","params":{...}}]}\n'
            f"Command: {message}", fast=True)
        jm = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not jm:
            return []
        allowed = {"open_app", "close_app", "type_text", "press", "hotkey",
                   "screenshot", "browse"}
        out = []
        for s in _json.loads(jm.group()).get("steps", [])[:6]:
            a = s.get("action", "")
            if a in allowed:
                risk = "high" if a == "close_app" else "low"
                out.append(Action(action_type=a, params=s.get("params", {}) or {},
                                  risk_level=risk))
        return out
    except Exception:
        return []


_STEP_LABELS = {"open_app": "name_or_path", "close_app": "process_name",
                "type_text": "text", "press": "key", "browse": "url"}

def _step_label(a) -> str:
    key = _STEP_LABELS.get(a.action_type)
    val = (a.params or {}).get(key, "") if key else ""
    val = str(val)
    return f"{a.action_type.replace('_', ' ')} {val[:40]}".strip()


def _route_action(message: str, session_id: str, intent: str) -> dict:
    """
    Turn a desktop/browser chat command into ExecutorAgent actions.
    Understands compound commands ("open notepad and type hello"), any verb
    form ("opening", "launch", "start up"), and falls back to the local LLM
    before ever giving up. Emits visible SSE (guardrail A). Risky actions
    return an inline approval prompt (guardrail B). NO direct execution here.
    """
    ex = _shared_executor()
    m = message.lower()

    # Browser navigation first (explicit URL or browser intent)
    if intent == "browser" or "navigate" in m or m.startswith("go to "):
        url = next((tok for tok in message.split() if tok.startswith("http")), "")
        _emit("browser", f"Navigating to {url or 'page'}", "info")
        action = Action(action_type="browse", params={"url": url}, risk_level="low")
        result = ex.execute_action(action)
        ok = result.get("success", False)
        return {"response": (f"Done: opened {url} ✓" if ok
                             else f"Couldn't navigate: {result.get('error','')}"),
                "intent": intent, "data": result}

    steps = _parse_command_steps(message)
    if not steps:
        _emit("executor", "Asking the local model to interpret the command", "info")
        steps = _llm_parse_steps(message)
    if not steps:
        return {"response": "I couldn't map that to an action. Try e.g. "
                            "'open notepad', 'open notepad and type hello', "
                            "'screenshot', or 'close calculator'.",
                "intent": intent, "data": {"error": "unparsed"}}

    # Risky step anywhere in the sequence → approval for the whole thing.
    # (Keeps the single-pending-action model: approve executes just that step.)
    risky = next((a for a in steps if ex.is_risky(a.action_type) or a.risk_level == "high"), None)
    if risky:
        ex.request_approval(session_id, risky)
        _emit("executor", f"[Approval Required] {_step_label(risky)}?", "warning")
        return {"response": f"This action may be destructive: {_step_label(risky)}. "
                            f"Reply 'yes' to confirm or 'cancel' to abort.",
                "intent": intent, "needs_approval": True}

    # Execute the sequence in order; brief settle time after opening an app so
    # a follow-up type_text lands in the newly opened window, not the browser.
    import time
    results, failed = [], None
    for i, action in enumerate(steps):
        _emit("executor", _step_label(action).capitalize(), "info")
        result = ex.execute_action(action)
        results.append({"step": _step_label(action), **result})
        if not result.get("success", False):
            failed = (action, result)
            break
        if action.action_type == "open_app" and i + 1 < len(steps):
            time.sleep(1.5)

    if failed:
        action, result = failed
        _emit("executor", f"{action.action_type} failed", "error")
        return {"response": f"Couldn't {_step_label(action)}: {result.get('error','')}",
                "intent": intent, "data": {"steps": results}}
    done = " → ".join(_step_label(a) for a in steps)
    _emit("executor", f"Done: {done}", "success")
    return {"response": f"Done: {done} ✓", "intent": intent,
            "data": {"steps": results}}
