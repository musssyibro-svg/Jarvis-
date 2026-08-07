"""
Regression tests for the stop button.

The bug these exist for, straight out of a runtime report:

    10:58:39 [control] Cancelling — stopping after the current step.
    10:58:43  check my qq messages   -> Cancelled, 0ms
    10:58:49  check my qq messages   -> Cancelled, 0ms
    11:00:22  open calculator        -> Cancelled, 0ms
    11:01:02  open calculator        -> Cancelled, 0ms
    11:01:24  open calculator        -> Cancelled, 0ms

One press of Stop, and every command after it died instantly for the rest of
the session. Cancel is global on purpose — one Stop button has to halt whatever
is running — but global also meant the flag outlived the thing it was aimed at.
"""

import threading

import pytest

from services import control


@pytest.fixture(autouse=True)
def _clean():
    control.clear()
    yield
    control.clear()


def test_cancel_with_nothing_running_is_cleared():
    control.cancel("test")
    assert control.is_cancelled()
    assert control.clear_stale()["cleared"] is True
    assert not control.is_cancelled()


def test_cancel_during_live_work_is_kept():
    """
    The other half, and the more important one: clearing a LIVE cancel would
    silently un-cancel work the user just asked to stop.
    """
    with control.run_scope():
        control.cancel("test")
        assert control.busy()
        assert control.clear_stale()["cleared"] is False
        assert control.is_cancelled()


def test_run_scope_does_not_leak():
    assert not control.busy()
    with control.run_scope():
        assert control.busy()
    assert not control.busy()


def test_run_scope_releases_on_exception():
    """A crash inside a chain must not leave Jarvis permanently 'busy'."""
    with pytest.raises(ValueError):
        with control.run_scope():
            raise ValueError("boom")
    assert not control.busy()


def test_nested_scopes_count():
    """The orchestrator runs a chain inside its own scope; both must unwind."""
    with control.run_scope():
        with control.run_scope():
            assert control.busy()
        assert control.busy(), "the inner scope exiting must not clear the outer one"
    assert not control.busy()


def test_checkpoint_raises_on_cancel():
    control.cancel("test")
    with pytest.raises(control.Cancelled):
        control.checkpoint("some step")


def test_checkpoint_is_a_no_op_when_nothing_is_pending():
    control.checkpoint("some step")  # must not raise, must not block


def test_pause_then_cancel_does_not_deadlock():
    """
    A worker blocked in a pause must still notice a cancel. Without the 1s
    wake-up it waits for a resume that is never coming, and Stop looks broken.
    """
    control.pause("test")
    done = threading.Event()
    raised = []

    def worker():
        try:
            control.checkpoint("step")
        except control.Cancelled:
            raised.append(True)
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    control.cancel("changed my mind")
    assert done.wait(timeout=5), "the paused worker never woke up for the cancel"
    assert raised == [True]


def test_resume_clears_pause():
    control.pause("test")
    assert control.is_paused()
    control.resume()
    assert not control.is_paused()
    control.checkpoint("step")


def test_status_is_readable():
    s = control.status()
    for key in ("mode", "can_pause", "can_resume"):
        assert key in s
