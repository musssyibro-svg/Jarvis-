"""
"It didn't work" and "it feels slow" were both unanswerable.

FAILURES. Every failed desktop action reduced to {"success": False,
"error": str(e)}. For the headless crash that cost an afternoon, str(e) was the
single word 'DISPLAY' — no traceback, no arguments, no way to tell which of
twenty actions raised it. The only way forward was to reproduce it.

SLOWNESS. Traces recorded what happened, never what it cost. There was no
component to point at, so "Jarvis is slow" stayed an opinion.

The security half matters as much as the diagnostic half: these records are
served over HTTP by a program that can be asked to type a password. Anything
that looks like a credential must not reach them.
"""

import pytest

from services import trace


@pytest.fixture(autouse=True)
def _clean():
    trace.reset_costs()
    trace._failures.clear()
    yield
    trace.reset_costs()
    trace._failures.clear()


# ── A failed action leaves enough to diagnose it ─────────────────────────────

def test_a_raising_action_records_the_traceback_not_just_the_message():
    from agents import desktop_agent as da

    out = da._run_action("hotkey", {"keys": None})     # TypeError inside the lambda
    assert out["success"] is False

    rec = trace.failures()[0]
    assert "TypeError" in rec["summary"]
    assert "desktop_agent.py" in rec["detail"], "no traceback — this is the whole bug"
    assert "hotkey" in rec["detail"], "the traceback must name the action that raised"


def test_an_unknown_action_is_not_recorded_as_a_crash():
    """A typo in a plan is a bad plan, not a failure worth a traceback."""
    from agents import desktop_agent as da

    assert da._run_action("teleport", {})["success"] is False
    assert trace.failures() == []


# ── Nothing secret reaches the buffer ────────────────────────────────────────

@pytest.mark.parametrize("key", ["password", "api_key", "auth_token",
                                 "session_cookie", "otp_code", "vault_secret"])
def test_credential_shaped_parameters_are_redacted(key):
    trace.failure("test", "boom", **{key: "hunter2"})
    assert trace.failures()[0]["context"][key] == "[redacted]"
    assert "hunter2" not in str(trace.failures()[0])


def test_typed_text_is_reduced_to_its_length():
    """
    'type my password' puts a credential in a parameter called `text`, which no
    name-based rule would catch. Only the shape is kept — enough to tell "the
    text never arrived" from "it arrived somewhere else".
    """
    trace.failure("desktop.type_text", "did not verify", text="correct horse battery")
    ctx = trace.failures()[0]["context"]
    assert ctx["text"] == "[21 chars]"
    assert "horse" not in str(trace.failures()[0])


def test_ordinary_context_survives():
    """Redaction that eats everything makes the record useless."""
    trace.failure("desktop.open_app", "not found", name_or_path="qq", step=2)
    ctx = trace.failures()[0]["context"]
    assert ctx["name_or_path"] == "qq"
    assert ctx["step"] == "2"


def test_the_buffer_is_bounded():
    """This runs for days at a time. An unbounded diagnostics list is a leak."""
    for i in range(trace._FAILURES + 40):
        trace.failure("test", f"boom {i}")
    assert len(trace._failures) == trace._FAILURES


# ── Where the time went ──────────────────────────────────────────────────────

def test_the_profile_names_the_slowest_component():
    for _ in range(5):
        trace.record_cost("ai.chat/ollama", 4000)
    for _ in range(50):
        trace.record_cost("desktop.click", 12)

    prof = trace.profile()
    assert prof["slowest"] == "ai.chat/ollama"
    row = next(r for r in prof["components"] if r["component"] == "ai.chat/ollama")
    assert row["calls"] == 5
    assert row["median_ms"] == 4000


def test_ranking_is_by_total_time_not_by_the_worst_single_call():
    """
    A 30-second call once an hour matters less than 400ms on every action.
    Ranking by max would put them the wrong way round, and send whoever reads
    it off optimising the wrong thing.
    """
    trace.record_cost("rare.but.huge", 30_000)
    for _ in range(200):
        trace.record_cost("constant.drag", 400)

    assert trace.profile()["slowest"] == "constant.drag"


def test_a_call_that_throws_is_still_measured():
    """A 40-second call that then fails is exactly the slowness worth seeing."""
    with pytest.raises(ValueError):
        with trace.timed("slow.and.broken"):
            raise ValueError("nope")

    assert trace.profile()["components"][0]["component"] == "slow.and.broken"


def test_every_chat_closes_its_trace(monkeypatch):
    """
    Only 8 of handle_chat's 41 return points called trace.finish, so most
    requests left a trace open: shown forever as "…", counted by summary() as
    not-yet-completed, and therefore never counted as FAILED. A failure
    dashboard that under-reports failures is worse than none.

    The open trace also stayed bound to the thread, so a background thread
    calling trace.step() appended to a request that had already been answered.
    """
    from adapters import commander_adapter as ca
    from services import ai_router
    monkeypatch.setattr(ai_router, "ask", lambda **k: "stubbed reply")

    ca.handle_chat("hello there", "trace-test")

    assert trace.current_id() is None, "the trace is still bound to this thread"
    t = trace.recent(1)[0]
    assert t["ok"] is not None, "finished with no verdict — invisible in diagnostics"
    assert t["duration_ms"] is not None


def test_steps_carry_their_own_cost():
    """
    took_ms is computed when the step is recorded. Differencing at_ms later
    only works while every caller records AFTER its work — an assumption a
    reader can't check and the first careless caller would break silently.
    """
    import time

    trace.start("test", "timing")
    time.sleep(0.02)
    trace.step("first")
    trace.step("second")
    steps = trace.recent(1)[0]["steps"]
    trace.finish("done")

    assert steps[0]["took_ms"] >= 15
    assert steps[1]["took_ms"] < 15, "the second step must not inherit the first's cost"
