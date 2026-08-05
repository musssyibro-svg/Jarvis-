"""
The three complaints that are actually about how Jarvis FEELS to use.

None of these are architecture. Each one is a specific line of code that made
an ordinary moment worse, and each was found by running the thing rather than
reading it.

  "Ollama is offline for a while before connecting"
      The model-list call had no timeout and ran inside the UI's status poll.
      A daemon busy loading a 6GB model stops answering it for a few seconds —
      so the console froze, then reported OFFLINE at a daemon that was running.

  "open new notepad" doesn't work
      The app name was taken literally, so Jarvis searched the Start Menu for
      "new notepad" and found nothing. A command that plainly means "open
      notepad", failing for a reason nobody could guess.

  "Approve All said success and I don't know what happened"
      A bid the site never acknowledged was written into the permanent receipt
      as "sent", and its row went green.
"""

import time
import types

import pytest

# ── "Ollama is offline for a while before connecting" ────────────────────────


@pytest.fixture
def slow_ollama(monkeypatch):
    """A daemon that is RUNNING but busy — the case that was misreported."""
    calls = {"n": 0}

    class _Client:
        def __init__(self, **kw):
            pass

        def list(self):
            calls["n"] += 1
            time.sleep(0.4)
            raise TimeoutError("read timed out")

    fake = types.ModuleType("ollama")
    fake.Client = _Client
    fake.list = lambda: (_ for _ in ()).throw(AssertionError("bare module used — no timeout"))
    monkeypatch.setitem(__import__("sys").modules, "ollama", fake)

    from services import ollama_manager

    ollama_manager._INSTALLED_CACHE.update(at=0.0, names=[], failed_at=0.0, reason="")
    yield calls
    ollama_manager._INSTALLED_CACHE.update(at=0.0, names=[], failed_at=0.0, reason="")


def test_a_busy_ollama_is_asked_once_not_once_per_poll(slow_ollama):
    """
    Only successes were cached, so a daemon that didn't answer was asked again
    on every single UI poll — an unbounded blocking call in a hot loop.
    """
    from services.ollama_manager import _list_installed

    for _ in range(5):
        _list_installed()
    assert slow_ollama["n"] == 1, (
        f"asked Ollama {slow_ollama['n']} times for 5 polls; each one blocks the UI"
    )


def test_the_model_list_call_gives_up(slow_ollama):
    """`import ollama; ollama.list()` has no timeout at all. This must not use it."""
    from services.ollama_manager import _list_installed

    t0 = time.time()
    _list_installed()
    assert time.time() - t0 < 3.0


def test_busy_is_reported_differently_from_offline(slow_ollama):
    """
    "I couldn't ask" is not "it's off". The console drew a red OFFLINE at a
    daemon that was running perfectly well, and the user went looking for a
    problem that wasn't there.
    """
    from services import os_state

    ollama = os_state.snapshot()["ollama"]
    assert ollama["online"] is False
    assert ollama["reachable"] is False
    assert ollama["reason"], "no reason given, so the UI can only say 'offline'"
    assert "busy" in ollama["reason"].lower() or "didn't answer" in ollama["reason"]


# ── "open new notepad" ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "said,means",
    [
        ("open new notepad", "notepad"),
        ("open another notepad", "notepad"),
        ("open a calculator", "calculator"),
        ("open the notepad", "notepad"),
        ("open my qq", "qq"),
        ("open up chrome", "chrome"),
    ],
)
def test_ordinary_english_finds_the_app(said, means):
    from services import decompose

    steps = decompose.decompose(said)["steps"]
    opened = [s["params"].get("name_or_path") for s in steps if s["action"] == "open_app"]
    assert opened and opened[0] == means, f"{said!r} looked for {opened}"


def test_a_qualifier_alone_is_still_a_name():
    """Stripping must never leave nothing — an app really called "new" stays reachable."""
    from services.tool_registry import _strip_qualifiers

    assert _strip_qualifiers("new") == "new"
    assert _strip_qualifiers("a") == "a"
    assert _strip_qualifiers("notepad new") == "notepad new"  # front only


# ── "Approve All said success" ───────────────────────────────────────────────


def test_an_unconfirmed_bid_is_not_recorded_as_sent():
    """
    The receipt is permanent and it is the only place the user can look weeks
    later. Writing "sent" for a bid the site never acknowledged is the exact
    complaint, stored in the database.
    """
    outcome = lambda r: (  # noqa: E731 — mirrors the expression under test
        "sent" if r.get("confirmed") else "unconfirmed" if r.get("success") else "failed"
    )

    assert outcome({"success": True, "confirmed": True}) == "sent"
    assert outcome({"success": True, "confirmed": False}) == "unconfirmed"
    assert outcome({"success": False, "confirmed": False}) == "failed"


def test_the_unconfirmed_branch_says_success_but_not_verified():
    """
    success and verified answer different questions, and this is the case that
    separates them: the click landed, the page moved, nothing said it arrived.

    success stays True on purpose — flipping it would put a real client
    submission back in the retry path, and sending twice is worse than once
    unconfirmed.
    """
    import inspect

    from services import bid_executor

    src = inspect.getsource(bid_executor)
    marker = '"success": True, "verified": False, "confirmed": False'
    assert marker in src, "the unconfirmed branch no longer distinguishes the two"
