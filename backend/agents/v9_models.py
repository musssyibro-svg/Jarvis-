"""
agents/v9_models.py — V9 typed data models (LOCKED spec).
Enforced dataclasses so goal/world/action objects can't drift into ad-hoc dicts.
"""
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Goal:
    goal_type: str
    objective: str
    constraints: dict = field(default_factory=dict)
    approval_required: bool = True
    success_condition: dict = field(default_factory=dict)
    goal_id: str = field(default_factory=lambda: _id("goal"))
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorldState:
    jobs: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    active_job: dict | None = None
    retries: int = 0
    screen_state: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Action:
    action_type: str
    params: dict = field(default_factory=dict)
    verify_condition: dict = field(default_factory=dict)
    risk_level: str = "low"   # low | medium | high
    action_id: str = field(default_factory=lambda: _id("act"))

    def to_dict(self) -> dict:
        return asdict(self)
