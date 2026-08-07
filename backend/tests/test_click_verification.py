"""
A click "succeeds" the moment pyautogui returns — which means the mouse moved,
not that anything responded.

Clicking a disabled button, a stale coordinate, or a window that closed half a
second ago all returned success, and the whole chain then proceeded as if the
UI had changed. That is the same false-Done problem as typing into a window
that never had focus, one layer over.

So click/press/hotkey now LOOK at the screen afterwards, and `verified` carries
what was seen. The three outcomes are deliberately distinct:

    saw a change      -> verified True
    saw NO change     -> verified False, and the step fails
    couldn't look     -> verified False, but the step PASSES with the doubt
                         stated. "No eyes" is not "didn't work", and failing
                         every click on a machine without mss/Pillow would
                         break chains that were fine.
"""

import pytest

from agents import desktop_agent as da


@pytest.fixture
def eyes(monkeypatch):
    """Control what Jarvis 'sees' before and after an action."""

    def _set(frames):
        seq = list(frames)
        monkeypatch.setattr(da, "_peek", lambda *a, **k: seq.pop(0) if seq else None)

    return _set


SAME = bytes([10] * 576)
DIFFERENT = bytes([200] * 576)


def test_a_click_that_changes_nothing_is_not_verified(monkeypatch, eyes):
    monkeypatch.setattr(da, "_require", lambda *a: None)
    monkeypatch.setattr(
        da, "pyautogui", type("p", (), {"click": staticmethod(lambda *a, **k: None)}), raising=False
    )
    monkeypatch.setattr(da, "_foreground_id", lambda: "same")
    eyes([SAME, SAME])

    out = da.click(100, 100)
    assert out["success"] is True, "the call did happen — that part is true"
    assert out["verified"] is False
    assert "landed on nothing" in out["verify_reason"]


def test_a_click_that_changes_the_screen_is_verified(monkeypatch, eyes):
    monkeypatch.setattr(da, "_require", lambda *a: None)
    monkeypatch.setattr(
        da, "pyautogui", type("p", (), {"click": staticmethod(lambda *a, **k: None)}), raising=False
    )
    monkeypatch.setattr(da, "_foreground_id", lambda: "same")
    eyes([SAME, DIFFERENT])

    out = da.click(100, 100)
    assert out["verified"] is True


def test_a_click_that_opens_a_window_is_verified_even_if_pixels_match(monkeypatch, eyes):
    """A new window is proof enough; the watched box may be off-screen now."""
    monkeypatch.setattr(da, "_require", lambda *a: None)
    monkeypatch.setattr(
        da, "pyautogui", type("p", (), {"click": staticmethod(lambda *a, **k: None)}), raising=False
    )
    fg = iter(["window-a", "window-b"])
    monkeypatch.setattr(da, "_foreground_id", lambda: next(fg))
    eyes([SAME, SAME])

    out = da.click(100, 100)
    assert out["verified"] is True
    assert "window changed" in out["verify_reason"]


def test_no_eyes_is_reported_as_doubt_not_as_failure(monkeypatch, eyes):
    monkeypatch.setattr(da, "_require", lambda *a: None)
    monkeypatch.setattr(
        da, "pyautogui", type("p", (), {"click": staticmethod(lambda *a, **k: None)}), raising=False
    )
    monkeypatch.setattr(da, "_foreground_id", lambda: "")
    eyes([None, None])

    out = da.click(100, 100)
    assert out["verified"] is False
    assert "can't see" in out["verify_reason"]

    # ...and the executor must let it through rather than aborting the chain.
    ok, reason = da._verify_action("click", {}, out)
    assert ok is True, "an unobservable click must not fail a working chain"
    assert "can't see" in reason


def test_an_observed_dead_click_does_fail_the_step(monkeypatch, eyes):
    """The other side: when we CAN see and nothing moved, that is a failure."""
    dead = {
        "success": True,
        "verified": False,
        "verify_reason": "Nothing on screen changed after clicking (5, 5). "
        "The click probably landed on nothing",
    }
    ok, reason = da._verify_action("click", {}, dead)
    assert ok is False
    assert "landed on nothing" in reason


def test_the_comparison_needs_a_real_difference(monkeypatch):
    """Anti-aliasing and a blinking cursor must not read as 'something happened'."""
    almost = bytes([10] * 570 + [14] * 6)  # a couple of pixels, barely
    assert da._changed(SAME, almost) is False
    assert da._changed(SAME, DIFFERENT) is True
    assert da._changed(None, SAME) is None
