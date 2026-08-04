"""
Two ways a model call goes wrong on a 16 GB machine, and neither looks like a bug.

1. THE BUDGET IS TOO BIG. Planning had no profile of its own, so it ran on the
   general "fast" budget: 400 tokens and a minute, for a job whose whole output
   is 3-6 short lines. Nothing fails — the user just watches a spinner.

2. A NEW KIND FALLS THROUGH THE MAP. select_model looked its kind up with
   [kind] in a dict holding only three roles. "batch" was already missing, so
   it raised KeyError into a bare `except` and came back as None — reported as
   "no model is available" on a machine where one plainly was. Adding
   "planner" would have joined it there.

The second is the more dangerous shape: a lookup that raises inside an except
that hides it. These tests exist so the next kind can't repeat it.
"""

import pytest
from providers.ollama_provider import OllamaProvider

from services.ollama_manager import LIMITS


def test_every_kind_has_a_budget():
    """A kind with no LIMITS entry silently gets 'fast' — a budget nobody chose."""
    for task, kind in OllamaProvider._KIND.items():
        assert kind in LIMITS, f"task '{task}' maps to kind '{kind}', which has no budget"


def test_every_kind_resolves_to_a_model_role(monkeypatch):
    """
    The KeyError-into-bare-except bug. Every kind must produce a model name
    when the router is unavailable, not None.
    """
    from services import ollama_manager

    monkeypatch.setattr(ollama_manager, "fast_model", lambda: "fast-model")
    monkeypatch.setattr(ollama_manager, "reasoning_model", lambda: "big-model")
    monkeypatch.setattr(ollama_manager, "vision_model", lambda: "eye-model")
    # model_router unavailable is the branch under test.
    import services.model_router as mr

    monkeypatch.setattr(mr, "pick", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

    prov = OllamaProvider()
    for task in OllamaProvider._KIND:
        assert prov.select_model(task), (
            f"task '{task}' resolved to no model at all — the user is told "
            f"nothing is installed on a machine where something is"
        )


def test_planning_is_cheaper_than_general_chat():
    """
    The point of the change. If someone later 'tidies' planner back onto the
    fast profile, this says why that was wrong.
    """
    p_tokens, p_ctx, p_secs = LIMITS["planner"]
    f_tokens, f_ctx, f_secs = LIMITS["fast"]
    assert p_tokens < f_tokens
    assert p_ctx <= f_ctx
    assert p_secs < f_secs


def test_the_planner_actually_asks_for_the_planner_budget():
    """
    The wiring, end to end. decompose used fast=True, which routes to "chat" —
    so a planner budget would have existed and never been used by anything.
    """
    seen = {}

    from services import planner_service

    def fake_call_model(prompt, history=None, fast=False, task=None):
        seen["task"] = task
        seen["fast"] = fast
        return "[no model]"  # force the keyword fallback, offline-safe

    import services.deepseek_service as ds

    original = ds.call_model
    ds.call_model = fake_call_model
    try:
        steps = planner_service.decompose("launch a small ecommerce site")
    finally:
        ds.call_model = original

    assert seen.get("task") == "planning", (
        f"planner asked for task={seen.get('task')!r}, so it gets some other "
        f"budget than the one tuned for it"
    )
    assert steps, "a bounded model failure must still produce an editable checklist"


@pytest.mark.parametrize(
    "task,kind",
    [("planner", "planner"), ("chat", "fast"), ("vision", "vision"), ("batch", "batch")],
)
def test_task_to_kind_stays_wired(task, kind):
    assert OllamaProvider._KIND[task] == kind
