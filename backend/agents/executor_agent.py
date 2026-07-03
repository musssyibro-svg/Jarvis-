"""
agents/executor_agent.py — V9 autonomy core (LOCKED spec).
Owns the loop: observe -> decide -> approval-if-risky -> act -> observe ->
verify -> recover. Uses typed Action model.

LOCKED RULE: ExecutorAgent EXCLUSIVELY owns pending actions, confirm, cancel,
the approval gate, and retry logic. Commander must never manage pending state.
"""
import threading

from agents.base_agent import BaseAgent
from agents.orchestrator import STATE
from agents.perception_agent import perception
from agents.v9_models import Action


class ExecutorAgent(BaseAgent):
    name = "executor"

    MAX_STEPS   = 25
    MAX_RETRIES = 3

    def __init__(self):
        self._pending = {}     # session_id -> Action   (OWNED HERE, nowhere else)
        self._pending_lock = threading.Lock()
        self.history  = []
        self._phase   = "start"
        self._plan    = None   # built lazily by _decide_planning
        self._plan_index = 0

    RISKY_ACTIONS = {
        "delete_file", "close_app", "kill_app", "run_command",
        "submit_application", "purchase", "payment",
        "browser_submit", "shutdown", "execute_shell",
    }

    def is_risky(self, action_type: str) -> bool:
        """Risk gate, owned here since ExecutorAgent owns the approval flow."""
        return action_type in self.RISKY_ACTIONS

    def execute_action(self, action) -> dict:
        """
        Public single-action entry for the chat adapter (interactive path).
        Runs the action, then a verification pass ONLY if perception is actually
        available. Running full screen analysis (LLaVA/OCR) after every chat
        command adds seconds of latency and violates the vision-on-demand rule;
        in the interactive path the human is watching the screen anyway.
        - verified True/False  -> perception checked and confirmed/contradicted
        - no 'verified' key    -> perception unavailable, could not check
        The strict always-verify loop remains in run_goal (autonomous path).
        """
        result = self._act(action)
        try:
            from agents.perception_agent import perception
            if perception.available():
                new_state = perception.observe(f"After {action.action_type}")
                result = {**result, "verified": self._verify(action, result, new_state)}
        except Exception:
            pass
        return result

    def _emit(self, msg: str, level: str = "info"):
        STATE.emit(self.name, msg, level)

    # ── Approval gate (exclusively owned by Executor) ───────────────────────────
    def request_approval(self, session: str, action: Action) -> dict:
        with self._pending_lock:
            self._pending[session] = action
        self._emit(f"Approval required: {action.action_type} (risk={action.risk_level})", "warning")
        return {"needs_approval": True, "pending": action.to_dict()}

    def confirm(self, session: str) -> dict:
        with self._pending_lock:
            action = self._pending.pop(session, None)
        if not action:
            return {"status": "no_pending", "message": "No pending action to confirm."}
        # Verified path. Semantics:
        #   success + verified False  -> perception CONTRADICTS the claim -> failed
        #   success + no verification -> perception unavailable; the human is
        #                                watching, trust the action's result
        result = self.execute_action(action)
        ok = result.get("success", False)
        note = None
        if ok and result.get("verified") is False:
            ok = False
        elif ok and "verified" not in result:
            note = "couldn't visually verify (OCR/vision not installed) — check your screen"
        out = {"status": "complete" if ok else "failed",
               "result": result, "action": action.to_dict()}
        if note:
            out["note"] = note
        return out

    def cancel(self, session: str) -> dict:
        with self._pending_lock:
            had = self._pending.pop(session, None)
        return {"status": "cancelled" if had else "nothing",
                "message": "Pending action cancelled." if had else "Nothing to cancel."}

    def has_pending(self, session: str) -> bool:
        with self._pending_lock:
            return session in self._pending

    # ── Autonomous loop ──────────────────────────────────────────────────────────
    def run_goal(self, task: dict) -> dict:
        goal_desc = task.get("type", "task")
        self._phase = "start"
        self._plan, self._plan_index = None, 0
        self._emit(f"Executor goal: {goal_desc}")
        steps = 0
        last_action_signature = None
        repeat_count = 0
        replans_used = 0
        MAX_REPLANS = 2   # bounds total replans per goal (separate from per-step retries)

        while steps < self.MAX_STEPS:
            steps += 1
            state  = perception.observe(f"Working toward: {goal_desc}")
            action = self._decide(task, state, steps)

            if action.action_type == "done":
                self._emit("Goal reached", "success")
                return {"status": "complete", "steps": steps}
            if action.action_type == "give_up":
                self._emit("Cannot proceed — escalating to human", "warning")
                return {"status": "failed", "steps": steps, "reason": "stuck"}

            # Stuck-state detection: same action repeated with no progress.
            sig = (action.action_type, tuple(sorted((action.params or {}).items())))
            if sig == last_action_signature:
                repeat_count += 1
            else:
                repeat_count = 0
            last_action_signature = sig
            if repeat_count >= 2:
                self._emit(f"Stuck: '{action.action_type}' repeated "
                           f"{repeat_count+1}x with no progress — replanning", "warning")
                if replans_used >= MAX_REPLANS or not self._replan(task, state):
                    self._emit("Replan budget exhausted — escalating to human", "error")
                    return {"status": "failed", "steps": steps, "reason": "stuck, replan exhausted"}
                replans_used += 1
                repeat_count = 0
                continue

            # Approval gate for risky actions
            if action.risk_level == "high" and not task.get("auto_apply"):
                session = task.get("session_id", "default")
                return self.request_approval(session, action) | {"steps": steps}

            ok = False
            for attempt in range(1, self.MAX_RETRIES + 1):
                result    = self._act(action)
                new_state = perception.observe(f"After {action.action_type}")
                if self._verify(action, result, new_state):
                    ok = True
                    break
                self._emit(f"Step {steps} verify failed ({attempt}/{self.MAX_RETRIES}) — recovering", "warning")
                self._recover(action, new_state, attempt)

            self.history.append({"step": steps, "action": action.action_type, "ok": ok})
            if len(self.history) > 500:
                self.history = self.history[-500:]
            if not ok:
                # Retries exhausted: try ONE bounded replan before giving up.
                if replans_used >= MAX_REPLANS:
                    self._emit(f"Step {steps} unrecoverable, replan budget exhausted — escalating", "error")
                    return {"status": "failed", "steps": steps,
                            "reason": f"verify failed for {action.action_type} (replan budget exhausted)"}
                self._emit(f"Step {steps} retries exhausted — attempting replan "
                           f"({replans_used+1}/{MAX_REPLANS})", "warning")
                if self._replan(task, state):
                    replans_used += 1
                    continue
                self._emit(f"Step {steps} unrecoverable — escalating", "error")
                return {"status": "failed", "steps": steps,
                        "reason": f"verify failed for {action.action_type}"}

        return {"status": "failed", "steps": steps, "reason": "max steps"}

    def _replan(self, task: dict, state: dict) -> bool:
        """
        Force a fresh plan: reset phase/plan so the next _decide() call rebuilds
        from current (possibly changed) state instead of repeating the same step.
        Returns False if there's nothing left to replan (caller should give up).
        """
        if self._phase == "start" and self._plan in (None, []):
            return False   # never made progress; replanning won't help
        self._phase = "start"
        self._plan, self._plan_index = None, 0
        self._emit("Replanning from current state", "info")
        return True

    # ── Decide / Act / Verify / Recover ──────────────────────────────────────────
    def _decide(self, task: dict, state: dict, step: int) -> Action:
        """
        Real per-task-type decision logic. Each call inspects current state and
        self._phase/self._plan to pick the NEXT action — not a hardcoded sequence.
        Supports: desktop, browser, vision, file, memory, planning, apply (legacy).
        """
        ttype = task.get("type", "")

        if ttype == "apply":
            return self._decide_apply(task, state, step)
        if ttype == "desktop":
            return self._decide_desktop(task, state, step)
        if ttype == "browser":
            return self._decide_browser(task, state, step)
        if ttype == "vision":
            return self._decide_vision(task, state, step)
        if ttype == "file":
            return self._decide_file(task, state, step)
        if ttype == "memory":
            return self._decide_memory(task, state, step)
        if ttype == "planning":
            return self._decide_planning(task, state, step)
        return Action(action_type="done")

    def _decide_apply(self, task: dict, state: dict, step: int) -> Action:
        job = task.get("job", {})
        url = job.get("url") or job.get("link")
        if self._phase == "start" and url:
            self._phase = "navigated"
            return Action(action_type="browse", params={"url": url},
                          verify_condition={"page_loaded": True}, risk_level="low")
        if self._phase in ("start", "navigated") and task.get("auto_apply"):
            self._phase = "submitted"
            return Action(action_type="submit_application",
                          params={"job": job, "proposal": task.get("proposal", {}),
                                 "queue_id": task.get("queue_id")},
                          verify_condition={"confirmation_visible": True},
                          risk_level="high")
        return Action(action_type="done")

    def _decide_desktop(self, task: dict, state: dict, step: int) -> Action:
        """Multi-step desktop tasks: a list of sub-steps consumed in order."""
        steps_list = task.get("steps", [])
        idx = self._plan_index
        if idx >= len(steps_list):
            return Action(action_type="done")
        s = steps_list[idx]
        self._plan_index += 1
        return Action(action_type=s.get("action", "done"), params=s.get("params", {}),
                      verify_condition=s.get("verify", {}),
                      risk_level=s.get("risk_level", "low"))

    def _decide_browser(self, task: dict, state: dict, step: int) -> Action:
        """Navigate -> perceive -> click target -> done, replanning from real DOM state."""
        url = task.get("url")
        target_text = task.get("click_text")
        if self._phase == "start" and url:
            self._phase = "navigated"
            return Action(action_type="browse", params={"url": url}, risk_level="low")
        if self._phase == "navigated" and target_text:
            self._phase = "clicked"
            return Action(action_type="click_element", params={"text": target_text}, risk_level="medium")
        return Action(action_type="done")

    def _decide_vision(self, task: dict, state: dict, step: int) -> Action:
        """Single observe; perception already ran this loop iteration via `state`."""
        self._phase = "done"
        return Action(action_type="done")

    def _decide_file(self, task: dict, state: dict, step: int) -> Action:
        op = task.get("op", "move")
        if self._phase != "start":
            return Action(action_type="done")
        self._phase = "done"
        if op == "move":
            return Action(action_type="move_file",
                          params={"src": task.get("src", ""), "dest_dir": task.get("dest_dir", "")},
                          risk_level="medium")
        return Action(action_type="done")

    def _decide_memory(self, task: dict, state: dict, step: int) -> Action:
        """Memory tasks are read/write side effects with no desktop action."""
        if self._phase == "start":
            self._phase = "recorded"
            try:
                from agents.memory_agent import MemoryAgent
                if task.get("write"):
                    MemoryAgent.record_outcome(
                        platform=task.get("platform", "executor"),
                        job_type=task.get("job_type", "task"),
                        proposal_snippet=task.get("snippet", ""),
                        won=task.get("won", False))
            except Exception:
                pass
        return Action(action_type="done")

    def _decide_planning(self, task: dict, state: dict, step: int) -> Action:
        """
        Real replanning: build (or rebuild) a sub-step list from the goal text
        using the existing Ollama fast() call, then execute it like a desktop task.
        """
        if self._plan is None:
            try:
                from services.deepseek_service import call_model
                import json as _json, re as _re
                prompt = (f"Break this into a JSON list of desktop steps. Goal: "
                         f"{task.get('objective','')}\nEach step: "
                         f'{{"action":"open_app|type_text|hotkey|press|screenshot",'
                         f'"params":{{...}}}}. Return ONLY the JSON list.')
                raw = call_model(prompt, fast=True)
                m = _re.search(r'\[.*\]', raw, _re.DOTALL)
                self._plan = _json.loads(m.group()) if m else []
            except Exception:
                self._plan = []
            self._plan_index = 0
        if self._plan_index >= len(self._plan):
            return Action(action_type="done")
        s = self._plan[self._plan_index]
        self._plan_index += 1
        return Action(action_type=s.get("action", "done"), params=s.get("params", {}))

    def _act(self, action: Action) -> dict:
        """
        V9: dispatch directly to desktop_agent / browser primitives.
        NO fallback to commander execution (commander no longer executes anything).
        Emits visible SSE for each meaningful action (UX guardrail A).
        """
        t = action.action_type
        p = action.params or {}
        try:
            if t == "browse":
                # Real navigation is wired in Phase 5 (browser-use). Until then,
                # do NOT report success for work that didn't happen.
                try:
                    from agents.browser_agent import navigate
                    ok = navigate(p.get("url"))
                    self._emit(f"[Browser] Navigated to {p.get('url','page')}", "success")
                    return {"success": bool(ok), "action": "browse"}
                except Exception as e:
                    self._emit(f"[Browser] navigation not available: {e}", "warning")
                    return {"success": False, "action": "browse",
                            "error": "browser navigation not implemented (Phase 5)"}
            if t == "submit_application":
                return self._submit_application(p)

            # Direct desktop primitives — no commander indirection
            from agents import desktop_agent as da
            if t == "open_app":
                self._emit(f"[Executor] Opening {p.get('name_or_path','')}")
                return da.open_app(p.get("name_or_path", ""))
            if t == "close_app":
                self._emit(f"[Executor] Closing {p.get('process_name','')}")
                return da.close_app(p.get("process_name", ""))
            if t == "screenshot":
                self._emit("[Executor] Taking screenshot")
                from agents import vision_agent as va
                return va.screenshot()
            if t == "click":
                self._emit("[Executor] Clicking")
                return da.click(p.get("x"), p.get("y"), p.get("button", "left"), p.get("clicks", 1))
            if t == "click_element":
                # Stage 2: locate an element by text in the structured DOM and click it.
                target = p.get("text", "")
                self._emit(f"[Executor] Locating '{target}' on page")
                from agents.perception_agent import perception
                view = perception.observe_browser()
                if not view.get("ok"):
                    return {"success": False, "error": f"perception failed: {view.get('error')}",
                            "action": t}
                el = perception.find_element(view["elements"], text=target, clickable_only=True)
                if not el:
                    return {"success": False, "error": f"element '{target}' not found",
                            "action": t, "candidates": len(view["elements"])}
                cx, cy = el["click_point"]
                self._emit(f"[Executor] Clicking '{el.get('text')}' at ({cx},{cy})")
                return da.click(cx, cy)
            if t == "type_text":
                self._emit("[Executor] Typing text")
                return da.type_text(p.get("text", ""))
            if t == "hotkey":
                self._emit("[Executor] Sending hotkey")
                return da.hotkey(*p.get("keys", []))
            if t == "press":
                self._emit("[Executor] Pressing key")
                return da.press(p.get("key", ""))
            if t == "move_file":
                self._emit("[Executor] Moving file")
                return da.move_file(p.get("src", ""), p.get("dest_dir", ""))

            # Unknown action: report cleanly, do NOT fall back to legacy execution
            if t == "parse":
                # Command couldn't be mapped to a concrete action. Return a clear
                # message rather than a confusing "unknown action" failure.
                return {"success": False, "action": "parse",
                        "error": "could not interpret command",
                        "message": "I couldn't map that to a concrete action. Try e.g. "
                                   "'open notepad', 'screenshot', or 'scan remoteok'."}
            return {"success": False, "error": f"unknown action '{t}'", "action": t}
        except Exception as e:
            return {"success": False, "error": str(e), "action": t}

    def _submit_application(self, p: dict) -> dict:
        """
        Real submission: calls bid_executor against the approved queue item if a
        queue_id is present, else falls back to a direct submit via bid_executor's
        own submit helper. Retries with backoff; no fake success.
        """
        import time
        qid = p.get("queue_id")
        job = p.get("job", {})
        proposal = p.get("proposal", {})
        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                from services import bid_executor
                if qid:
                    self._emit(f"[Browser] Submitting application (queue #{qid}, "
                               f"attempt {attempt}/{self.MAX_RETRIES})")
                    result = bid_executor.execute_queue_item(qid)
                else:
                    self._emit(f"[Browser] Submitting application directly "
                               f"(attempt {attempt}/{self.MAX_RETRIES})")
                    result = bid_executor._run_submit(
                        job.get("url") or job.get("link", ""),
                        proposal.get("proposal_text", ""))
                if result.get("success"):
                    self._emit("[Browser] Application submitted ✓", "success")
                    return {"success": True, "action": "submit_application", "result": result}
                last_error = result.get("message") or result.get("error") or "submission failed"
                self._emit(f"[Browser] Submit failed: {last_error}", "warning")
            except Exception as e:
                last_error = str(e)
                self._emit(f"[Browser] Submit error: {last_error}", "error")
            if attempt < self.MAX_RETRIES:
                time.sleep(2 * attempt)   # backoff before retry

        return {"success": False, "action": "submit_application",
                "error": f"submission failed after {self.MAX_RETRIES} attempts: {last_error}"}

    def _verify(self, action: Action, result: dict, new_state: dict) -> bool:
        # 1. action itself must report success
        if not result.get("success", False):
            return False
        # 2. if perception explicitly failed, we CANNOT confirm -> treat as NOT verified.
        #    (Previously this returned the action's own success flag, which meant
        #    "couldn't verify, therefore success" — the opposite of a safety gate.)
        if new_state.get("ok") is False and new_state.get("error"):
            self._emit(f"Cannot verify {action.action_type}: perception failed "
                       f"({new_state.get('error')})", "warning")
            return False
        return True

    def _recover(self, action: Action, state: dict, attempt: int = 1):
        import time, os
        backoff = min(2 * attempt, 6)
        self._emit(f"Recovery: retry {action.action_type} in {backoff}s "
                   f"(attempt {attempt}/{self.MAX_RETRIES})", "info")
        if not os.environ.get("JARVIS_TEST_MODE"):
            time.sleep(backoff)
