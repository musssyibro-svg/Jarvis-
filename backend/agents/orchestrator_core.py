"""
agents/orchestrator_core.py — V9 central brain (LOCKED spec).
State machine with an EXPLICIT transition table. Owns Goal + WorldState +
AgentState + progress + retry counter. Uses typed models from v9_models.
Absorbs services/automation_engine.py responsibilities.
"""
import threading
from enum import Enum

from agents.orchestrator import STATE  # existing SSE feed
from agents.v9_models import Goal, WorldState

# One workflow at a time. The UI polls aggressively and users double-click —
# without this, every POST /automation/start stacked another full scan
# (the duplicate [SCOUT] runs in the field logs).
_RUN_LOCK = threading.Lock()


class AgentState(Enum):
    IDLE       = 0
    PLANNING   = 1
    SCOUTING   = 2
    PROPOSING  = 3
    EXECUTING  = 4
    VERIFYING  = 5
    RECOVERING = 6
    COMPLETE   = 7
    FAILED     = 8
    # A user halt is NOT a failure. Filing it as FAILED made the console
    # report an error for something the user deliberately did, and
    # poisoned the reliability figures experience.py learns from.
    STOPPED    = 9


# Explicit, mandatory transition table (allowed next states per current state).
TRANSITIONS = {
    AgentState.IDLE:       {AgentState.PLANNING},
    AgentState.PLANNING:   {AgentState.SCOUTING, AgentState.FAILED, AgentState.STOPPED},
    AgentState.SCOUTING:   {AgentState.PROPOSING, AgentState.FAILED, AgentState.COMPLETE,
                            AgentState.STOPPED},
    AgentState.PROPOSING:  {AgentState.EXECUTING, AgentState.FAILED, AgentState.COMPLETE,
                            AgentState.STOPPED},
    AgentState.EXECUTING:  {AgentState.VERIFYING, AgentState.RECOVERING, AgentState.STOPPED},
    AgentState.VERIFYING:  {AgentState.COMPLETE, AgentState.RECOVERING, AgentState.STOPPED},
    AgentState.RECOVERING: {AgentState.EXECUTING, AgentState.FAILED, AgentState.STOPPED},
    AgentState.COMPLETE:   set(),
    AgentState.FAILED:     set(),
    AgentState.STOPPED:    set(),
}

MAX_RETRIES = 3


class IllegalTransition(Exception):
    pass


class OrchestratorCore:
    MAX_TRANSITIONS = 100

    def __init__(self):
        self.state       = AgentState.IDLE
        self.goal: Goal | None = None
        self.world       = WorldState()
        self.progress    = 0
        self.retries     = 0
        self.error       = None
        self._transitions = 0
        self._skipped = False   # True when a run was skipped due to collision
        self._cancelled = False # True when the user cancelled (not a failure)

    # ── SSE structured event ────────────────────────────────────────────────────
    _UI_STATE = {
        "IDLE": "idle", "PLANNING": "thinking", "SCOUTING": "scouting",
        "PROPOSING": "proposing", "EXECUTING": "executing", "VERIFYING": "executing",
        "RECOVERING": "thinking", "COMPLETE": "speaking", "FAILED": "approval",
        "STOPPED": "idle",
    }

    def _emit(self, agent: str, message: str, level: str = "info"):
        ui = self._UI_STATE.get(self.state.name, "thinking")
        STATE.emit(agent, f"[{self.state.name}] {message}", level, state=ui)

    # ── Publish state to the shared bus ─────────────────────────────────────────
    def _sync(self):
        """
        Write running/stage/progress into the SHARED STATE the UI reads.

        This is the freelance control bug in one method. The core only ever
        called STATE.emit(), which appends to the LOG FEED — it never wrote the
        status fields. GET /orchestrator/status returns STATE.get(), which the
        Earn page and sidebar poll. So the log scrolled with real progress while
        every status field said idle: the pipeline ran, and the UI had no idea.

        Must be called on EVERY transition, not just at start and end, or the
        stage indicator freezes on whatever it saw last.
        """
        running = self.state not in (AgentState.IDLE, AgentState.COMPLETE,
                                     AgentState.FAILED, AgentState.STOPPED)
        try:
            STATE.set(running=running,
                      stage=self.state.name.lower(),
                      progress=self.progress,
                      error=self.error,
                      stopped=self.state == AgentState.STOPPED)
        except Exception:
            pass      # the bus must never be able to break the workflow

    # ── Stop ────────────────────────────────────────────────────────────────────
    def request_stop(self, reason: str = "user asked") -> dict:
        """
        Ask the run to halt at the next safe point.

        Delegates to services.control rather than adding a second stop
        mechanism. Two independent stop paths that don't know about each other
        is exactly how this got broken in the first place — there were already
        two stop ROUTES, and neither reached the running code.
        """
        try:
            from services import control
            return control.cancel(reason)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    # ── Guarded transition (enforces the table) ─────────────────────────────────
    def transition_state(self, target: AgentState):
        if target not in TRANSITIONS[self.state]:
            raise IllegalTransition(f"{self.state.name} -> {target.name} not allowed")
        self.state = target

    # ── Goal entry point ────────────────────────────────────────────────────────
    def set_goal(self, goal: Goal):
        # Full reset. The core is a SINGLETON now, so a previous run's terminal
        # state would otherwise make the next set_goal raise IllegalTransition
        # (COMPLETE has no allowed successors).
        self.goal     = goal
        self.world    = WorldState()
        self.progress = 0
        self.retries  = 0
        self.error    = None
        self._transitions = 0
        self._skipped = False
        self._cancelled = False
        self.state    = AgentState.IDLE
        try:
            from services import control
            control.clear()          # a stale cancel must not kill a new goal
        except Exception:
            pass
        self.transition_state(AgentState.PLANNING)
        self._sync()
        self._emit("orchestrator", f"Goal set: {goal.goal_type} / {goal.objective}")

    # ── Full workflow loop ──────────────────────────────────────────────────────
    def run_full_workflow(self) -> dict:
        if self.state == AgentState.IDLE:
            self.error = "no goal set"
            self.state = AgentState.FAILED
            return self.snapshot()

        # Wait briefly for an in-flight workflow instead of instantly failing.
        # Instant-fail is why the income engine logged "Cycle #N done (FAILED)"
        # whenever a manual scan overlapped a scheduled one — nothing was
        # actually wrong, the two just collided.
        if not _RUN_LOCK.acquire(timeout=90):
            self.error = "another workflow is already running"
            self.state = AgentState.FAILED
            self._skipped = True      # a collision, NOT a real failure
            self._emit("orchestrator",
                       "Another workflow is already running — skipping this start "
                       "(not an error)", "info")
            return self.snapshot()
        try:
            self._sync()
            return self._run_locked()
        finally:
            _RUN_LOCK.release()
            self._sync()        # belt and braces: never leave running=True

    def _run_locked(self) -> dict:
        from services import control
        while self.state not in (AgentState.COMPLETE, AgentState.FAILED):
            # Interruption point. BETWEEN states, never inside one — pausing
            # halfway through a bid submission would leave a half-filled form on
            # a live freelance site. The cost is that a pause takes as long as
            # the current step; the benefit is Jarvis is never interrupted into
            # an inconsistent state.
            try:
                control.checkpoint(step=self.state.name.lower())
            except control.Cancelled:
                self.error = None            # a user stop is not an error
                self.state = AgentState.STOPPED
                self._cancelled = True
                self._emit("orchestrator", "Stopped — halted cleanly between "
                                           "steps, nothing left half-done.", "warning")
                break

            self._transitions += 1
            if self._transitions > self.MAX_TRANSITIONS:
                self.error = "max transitions exceeded"
                self.state = AgentState.FAILED
                break
            handler = {
                AgentState.PLANNING:   self._plan,
                AgentState.SCOUTING:   self._scout,
                AgentState.PROPOSING:  self._propose,
                AgentState.EXECUTING:  self._execute,
                AgentState.VERIFYING:  self._verify,
                AgentState.RECOVERING: self._recover,
            }.get(self.state)
            if handler is None:
                self.error = f"no handler for {self.state.name}"
                self.state = AgentState.FAILED
                break
            try:
                handler()
            except Exception as e:
                # A handler that throws used to escape the loop entirely, which
                # left STATE.running stuck True forever — after that every start
                # was refused as "already running" until the backend restarted.
                self.error = f"{self.state.name.lower()} failed: {e}"
                self.state = AgentState.FAILED
                self._emit("orchestrator", self.error, "error")
                break
            self._sync()        # publish after EVERY transition, not just at the ends

        self._emit("orchestrator",
                   f"Workflow finished: {self.state.name}"
                   + (f" ({self.error})" if self.error else ""),
                   "success" if self.state == AgentState.COMPLETE
                   else "warning" if self.state == AgentState.STOPPED else "error")
        # ALWAYS publish the terminal state. If this is skipped on any path,
        # running stays True and the next start is refused forever.
        self._sync()
        try:
            from services import control
            control.clear()      # don't let this run's stop bleed into the next
        except Exception:
            pass
        self._learn()
        return self.snapshot()

    def _learn(self) -> None:
        """
        Hand the finished run to the brain so a lesson gets recorded.

        brain_decision.after_goal() and reflection.reflect() both existed and
        neither was ever called from here, which is why a runtime report after
        hours of use said `reflections: 0`. A learning loop nothing feeds is
        indistinguishable from no learning loop at all.

        Off the request thread: reflect() may consult the fast model, and this
        machine has no RAM to spare on the critical path. A stopped run is
        skipped — the user interrupting is not a lesson about the task.
        """
        if self._cancelled or self._skipped:
            return
        ok = self.state == AgentState.COMPLETE
        steps = self._outcome_steps()
        goal = self.goal

        def _bg():
            try:
                from services import brain_decision
                brain_decision.after_goal(goal.goal_type, goal.objective, ok, steps)
            except Exception:
                pass

        try:
            import threading
            threading.Thread(target=_bg, daemon=True).start()
        except Exception:
            pass

    def _outcome_steps(self) -> list[dict]:
        """
        What this run actually did, in the shape reflection.reflect() reads.

        Built from counts the handlers already recorded — jobs found, proposals
        drafted, applications sent — not from a narrative. A reflection assembled
        from real numbers can be wrong about the lesson; one assembled from a
        model's guess about the run can be wrong about the run.
        """
        ss = self.world.screen_state or {}
        jobs = len(self.world.jobs or [])
        props = len(self.world.proposals or [])
        applied = int(ss.get("applied") or 0)
        need_prop = bool((ss.get("plan") or {}).get("need_proposal"))
        need_exec = bool((ss.get("plan") or {}).get("need_execute"))

        steps = [{"step": 1, "action": "scout", "success": jobs > 0,
                  "verified": jobs > 0,
                  "verify_reason": f"{jobs} job(s) qualified"}]
        if need_prop:
            steps.append({"step": 2, "action": "propose", "success": props > 0,
                          "verified": props > 0,
                          "verify_reason": f"{props} proposal(s) drafted"})
        if need_exec:
            steps.append({"step": len(steps) + 1, "action": "apply",
                          "success": applied > 0, "verified": applied > 0,
                          "attempts": self.retries + 1,
                          "verify_reason": f"{applied} application(s) sent"})
        if self.error:
            steps.append({"step": len(steps) + 1, "action": self.state.name.lower(),
                          "success": False, "verified": False,
                          "error": self.error, "verify_reason": self.error})
        return steps

    # alias kept for older callers
    run = run_full_workflow

    # ── Handlers ─────────────────────────────────────────────────────────────────
    def _plan(self):
        self._emit("orchestrator", "Decomposing goal")
        c = self.goal.constraints or {}
        self.world.screen_state = {"plan": {
            "need_proposal": bool(self.goal.goal_type == "freelance_application"
                                  or c.get("auto_apply")),
            "need_execute":  bool(c.get("auto_apply")),
        }}
        self.progress = 10
        self.transition_state(AgentState.SCOUTING)

    def _scout(self):
        c0 = self.goal.constraints or {}
        per = int(c0.get("max_per_platform") or c0.get("max_jobs") or 10)
        plats = c0.get("platforms", [])
        # Say the number out loud. If the limit you set isn't in this line, the
        # setting didn't reach the scan — which is exactly what was happening.
        self._emit("scout", f"Scanning {len(plats) or '?'} platform(s), "
                            f"up to {per} each")
        try:
            from agents.scout_agent import ScoutAgent
            c = self.goal.constraints or {}
            res = ScoutAgent().run({
                "platforms":        c.get("platforms", ["remoteok", "weworkremotely", "hubstaff"]),
                # Honour what the user actually set. This read max_jobs, which
                # the start route never populated correctly, so every scan used
                # the default no matter what you chose.
                "max_per_platform": int(c.get("max_per_platform") or c.get("max_jobs") or 10),
                "category":         self.goal.objective,
            })
            self.world.jobs = res.get("jobs", [])
            STATE.update_stats(jobs_found=len(self.world.jobs))
            self._emit("scout", f"{len(self.world.jobs)} jobs found", "success")

            # Score + filter: bad-fit jobs are dropped HERE so ProposalAgent
            # only ever writes for jobs worth bidding on.
            from agents.score_agent import ScoreAgent
            from services.profile_service import get_profile
            profile = get_profile()
            sres = ScoreAgent().run({
                "jobs":        self.world.jobs,
                "min_score":   int(c.get("min_score", profile.get("min_score", 30))),
                "your_skills": c.get("your_skills") or profile.get("skills", ""),
            })
            qualified = sres.get("qualified", [])
            STATE.update_stats(jobs_qualified=len(qualified))
            self._emit("score", f"{len(qualified)}/{len(self.world.jobs)} jobs qualified "
                                f"(rest ignored as bad fit)", "success")
            if qualified:
                try:
                    from services import event_bus
                    event_bus.publish("job.found", {"count": len(qualified),
                                      "top": qualified[0].get("title", "")[:60]})
                except Exception:
                    pass
            self.world.jobs = qualified
        except Exception as e:
            self.error = f"scout failed: {e}"
            self.transition_state(AgentState.FAILED)
            return
        self.progress = 35
        if not self.world.jobs:
            self._emit("orchestrator", "No jobs found", "warning")
            self.transition_state(AgentState.COMPLETE)
            return
        self.transition_state(AgentState.PROPOSING
                              if self.world.screen_state["plan"]["need_proposal"]
                              else AgentState.COMPLETE)

    def _propose(self):
        self._emit("proposal", f"Drafting proposals for {len(self.world.jobs)} job(s)")
        try:
            from agents.proposal_agent import ProposalAgent
            c = self.goal.constraints or {}
            # ONE batch call with the contract ProposalAgent actually reads
            # ("qualified_jobs"). The old per-job {"job": ...} call always
            # iterated an empty list — the permanent "0 generated" bug.
            res = ProposalAgent().run({
                "qualified_jobs": self.world.jobs,
                "your_name":      c.get("your_name", ""),
                "your_skills":    c.get("your_skills", ""),
                "max_generate":   int(c.get("max_generate") or c.get("max_jobs") or 10),
            })
            generated = res.get("generated", [])
            for entry in generated:
                self.world.proposals.append({"job": entry, "proposal": entry})
            STATE.update_stats(proposals_gen=len(generated))
            self._emit("proposal", f"{len(generated)} drafted", "success")

            # Queue every draft for human review — this is what fills the
            # Auto Mode QUEUE tab. Previously nothing ever reached the queue
            # unless auto_apply was set, so the tab stayed empty forever.
            from agents.orchestrator import _queue_for_approval
            _queue_for_approval(generated)
            self._emit("orchestrator",
                       f"{len(generated)} proposal(s) queued — review them in "
                       f"Freelance ▸ Auto Mode ▸ Queue", "success")

            # Optional hands-off mode: submit without the extra approve click.
            try:
                from services.profile_service import get_profile
                if generated and (c.get("auto_submit") or get_profile().get("auto_submit")):
                    from datetime import datetime, timezone

                    from models.db import conn
                    now = datetime.now(timezone.utc).isoformat()
                    with conn() as db:
                        db.execute("UPDATE automation_queue SET status='approved',"
                                   "processed_at=? WHERE status='pending'", (now,))
                    from services.bid_executor import execute_all_approved
                    execute_all_approved()
                    self._emit("executor", "auto_submit is ON — submitting queued bids", "warning")
            except Exception as e:
                self._emit("executor", f"auto-submit skipped: {e}", "warning")
        except Exception as e:
            self.error = f"proposal failed: {e}"
            self.transition_state(AgentState.FAILED)
            return
        self.progress = 60
        self.transition_state(AgentState.EXECUTING
                              if self.world.screen_state["plan"]["need_execute"]
                              else AgentState.COMPLETE)

    def _execute(self):
        self._emit("executor", "Executing applications")
        try:
            from agents.executor_agent import ExecutorAgent
            ex = ExecutorAgent()
            applied = 0
            for item in self.world.proposals:
                self.world.active_job = item["job"]
                outcome = ex.run_goal({
                    "type": "apply", "job": item["job"],
                    "proposal": item["proposal"],
                    "auto_apply": (self.goal.constraints or {}).get("auto_apply", False),
                })
                if outcome.get("status") == "complete":
                    applied += 1
            self.world.screen_state["applied"] = applied
            self._emit("executor", f"{applied} application(s) done", "success")
            self.transition_state(AgentState.VERIFYING)
        except Exception as e:
            self.error = f"executor failed: {e}"
            self.transition_state(AgentState.RECOVERING)

    def _verify(self):
        self._emit("orchestrator", "Verifying outcomes")
        applied = self.world.screen_state.get("applied", 0)
        cond = self.goal.success_condition or {}
        need = cond.get("min_applied", 0)
        try:
            from agents.memory_agent import MemoryAgent
            MemoryAgent.record_outcome(platform="orchestrator",
                                       job_type=self.goal.goal_type,
                                       proposal_snippet=f"{applied} applied",
                                       won=applied >= max(need, 1))
        except Exception:
            pass
        if applied >= need:
            self.progress = 100
            self.transition_state(AgentState.COMPLETE)
        else:
            self._emit("orchestrator", f"Success condition not met ({applied}/{need})", "warning")
            self.transition_state(AgentState.RECOVERING)

    def _recover(self):
        self.retries += 1
        self.world.retries = self.retries
        if self.retries > MAX_RETRIES:
            self.error = f"recovery exhausted after {self.retries} tries"
            self._emit("orchestrator", self.error, "error")
            self.transition_state(AgentState.FAILED)
        else:
            self._emit("orchestrator", f"Recovery attempt {self.retries}/{MAX_RETRIES}", "warning")
            self.transition_state(AgentState.EXECUTING)

    # ── Snapshot ─────────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {
            "skipped":     getattr(self, "_skipped", False),
            # A cancel is a user decision, not a fault. Reporting it as a
            # failure would make the console cry wolf and pollute the
            # reliability numbers experience.py learns from.
            "cancelled":   getattr(self, "_cancelled", False),
            "state":       self.state.name,
            "goal":        self.goal.to_dict() if self.goal else None,
            "progress":    self.progress,
            "world_state": self.world.to_dict(),
            "retries":     self.retries,
            "error":       self.error,
        }


core = OrchestratorCore()


# ── Module singleton ─────────────────────────────────────────────────────────
#
# Every route used to do `core = OrchestratorCore()` — a throwaway local. The
# work ran on that instance and then vanished, while /v9/state read a
# module-level object nothing had ever touched, so it reported IDLE during a
# live run. One shared instance, one truth.
_CORE: "OrchestratorCore | None" = None
_CORE_LOCK = threading.Lock()


def get_core() -> "OrchestratorCore":
    global _CORE
    with _CORE_LOCK:
        if _CORE is None:
            _CORE = OrchestratorCore()
        return _CORE


# Back-compat for modules that imported the name directly.
core = get_core()
