"""
agents/orchestrator_core.py — V9 central brain (LOCKED spec).
State machine with an EXPLICIT transition table. Owns Goal + WorldState +
AgentState + progress + retry counter. Uses typed models from v9_models.
Absorbs services/automation_engine.py responsibilities.
"""
from enum import Enum

from agents.orchestrator import STATE          # existing SSE feed
from agents.v9_models import Goal, WorldState


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


# Explicit, mandatory transition table (allowed next states per current state).
TRANSITIONS = {
    AgentState.IDLE:       {AgentState.PLANNING},
    AgentState.PLANNING:   {AgentState.SCOUTING, AgentState.FAILED},
    AgentState.SCOUTING:   {AgentState.PROPOSING, AgentState.FAILED, AgentState.COMPLETE},
    AgentState.PROPOSING:  {AgentState.EXECUTING, AgentState.FAILED, AgentState.COMPLETE},
    AgentState.EXECUTING:  {AgentState.VERIFYING, AgentState.RECOVERING},
    AgentState.VERIFYING:  {AgentState.COMPLETE, AgentState.RECOVERING},
    AgentState.RECOVERING: {AgentState.EXECUTING, AgentState.FAILED},
    AgentState.COMPLETE:   set(),
    AgentState.FAILED:     set(),
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

    # ── SSE structured event ────────────────────────────────────────────────────
    _UI_STATE = {
        "IDLE": "idle", "PLANNING": "thinking", "SCOUTING": "scouting",
        "PROPOSING": "proposing", "EXECUTING": "executing", "VERIFYING": "executing",
        "RECOVERING": "thinking", "COMPLETE": "speaking", "FAILED": "approval",
    }

    def _emit(self, agent: str, message: str, level: str = "info"):
        ui = self._UI_STATE.get(self.state.name, "thinking")
        STATE.emit(agent, f"[{self.state.name}] {message}", level, state=ui)

    # ── Guarded transition (enforces the table) ─────────────────────────────────
    def transition_state(self, target: AgentState):
        if target not in TRANSITIONS[self.state]:
            raise IllegalTransition(f"{self.state.name} -> {target.name} not allowed")
        self.state = target

    # ── Goal entry point ────────────────────────────────────────────────────────
    def set_goal(self, goal: Goal):
        self.goal     = goal
        self.world    = WorldState()
        self.progress = 0
        self.retries  = 0
        self.error    = None
        self._transitions = 0
        self.transition_state(AgentState.PLANNING)
        self._emit("orchestrator", f"Goal set: {goal.goal_type} / {goal.objective}")

    # ── Full workflow loop ──────────────────────────────────────────────────────
    def run_full_workflow(self) -> dict:
        if self.state == AgentState.IDLE:
            self.error = "no goal set"
            self.state = AgentState.FAILED
            return self.snapshot()

        while self.state not in (AgentState.COMPLETE, AgentState.FAILED):
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
            handler()

        self._emit("orchestrator",
                   f"Workflow finished: {self.state.name}"
                   + (f" ({self.error})" if self.error else ""),
                   "success" if self.state == AgentState.COMPLETE else "error")
        return self.snapshot()

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
        self._emit("scout", "Scanning platforms")
        try:
            from agents.scout_agent import ScoutAgent
            c = self.goal.constraints or {}
            res = ScoutAgent().run({
                "platforms":        c.get("platforms", ["remoteok", "weworkremotely", "hubstaff"]),
                "max_per_platform": c.get("max_jobs", 5),
                "category":         self.goal.objective,
            })
            self.world.jobs = res.get("jobs", [])
            self._emit("scout", f"{len(self.world.jobs)} jobs found", "success")
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
            agent = ProposalAgent()
            c = self.goal.constraints or {}
            for job in self.world.jobs[: c.get("max_jobs", 5)]:
                res = agent.run({"job": job,
                                 "your_name":   c.get("your_name", ""),
                                 "your_skills": c.get("your_skills", "")})
                self.world.proposals.append({"job": job, "proposal": res})
            self._emit("proposal", f"{len(self.world.proposals)} drafted", "success")
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
            "state":       self.state.name,
            "goal":        self.goal.to_dict() if self.goal else None,
            "progress":    self.progress,
            "world_state": self.world.to_dict(),
            "retries":     self.retries,
            "error":       self.error,
        }


core = OrchestratorCore()
