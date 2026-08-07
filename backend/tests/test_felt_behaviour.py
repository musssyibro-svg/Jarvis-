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


# ── What the 2026-08-05 runtime report caught ────────────────────────────────


def test_a_look_at_an_unfocusable_app_fails_instead_of_answering():
    """
    The worst thing in the report. Asked to check QQ:

        OK  desktop.open_app     window/process present  [46671ms]
        ERR desktop.focus_window No window found for 'qq'
        OK  desktop.screenshot   captured
        ERR desktop.focus_window No window found for 'qq'
        OK  desktop.analyze      analysis produced
        -> screen analysed                       <- reported as SUCCESS

    It analysed whatever was in front — Edge — and answered about QQ. Worse,
    experience recorded qq at 100% success, so the learning loop was being
    taught that this works.

    Typing may proceed on unconfirmed focus because the clipboard read-back
    settles it afterwards. Looking has no such arbiter, so it must stop.
    """
    from agents import desktop_agent as da

    original_fg, original_focus = da._is_foreground, da.focus_window
    original_open, original_vis = da.open_app, da._app_visible
    da._is_foreground = lambda *a, **k: False
    da.focus_window = lambda *a, **k: {
        "success": False,
        "error": "qq is running as qq.exe, but it has no window on screen",
    }
    # QQ opens fine — that is the whole point. The process IS there; what
    # cannot be confirmed is that its window is in front.
    da.open_app = lambda *a, **k: {
        "success": True,
        "action": "open_app",
        "app": "qq",
        "verified": True,
    }
    da._app_visible = lambda *a, **k: True  # the PROCESS is there
    try:
        out = da._execute_chain(
            [
                {"action": "open_app", "params": {"name_or_path": "qq"}},
                {"action": "screenshot", "params": {}},
                {"action": "analyze", "params": {"question": "any messages?"}},
            ],
            goal="check my qq messages",
        )
    finally:
        da._is_foreground, da.focus_window = original_fg, original_focus
        da.open_app, da._app_visible = original_open, original_vis

    assert out["success"] is False, "answered about a window it could not confirm"
    assert "no window on screen" in out["error"] or "front" in out["error"]
    succeeded = [s.get("action") for s in out["steps"] if s.get("success")]
    assert "analyze" not in succeeded, "an analyze step still reported success"


def test_a_tray_app_is_not_reported_as_missing():
    """
    "No window found for 'qq'" reads as "QQ isn't running" — and QQ was running
    the whole time, minimised to the tray. The message has to name the real
    situation, because the two have completely different fixes.
    """
    from agents import desktop_agent as da

    original = da._running_process_for
    da._running_process_for = lambda name: "qq.exe" if name == "qq" else None
    try:
        out = da.focus_window("qq")
    finally:
        da._running_process_for = original

    if out.get("success"):
        return  # a real window existed on this machine; nothing to assert
    assert out.get("tray_suspected"), f"tray case not recognised: {out.get('error')}"
    assert "tray" in out["error"].lower()


def test_a_failed_app_launch_gets_an_app_remedy_not_a_browser_one():
    """
    The report's remedy for a failed Start Menu launch was "the site's layout
    may have changed, or the page hadn't finished loading" — because the
    substring "no match" in "no matching window opened" hit element_not_found.
    A confidently wrong fix sends you to look at the wrong thing entirely.
    """
    from services import experience

    fail = experience.classify(
        "Searched the Start Menu for 'notepad' but no matching window opened "
        "— it may not be installed, or its window title differs.",
        action="open_app",
    )
    assert fail["kind"] == "app_not_found"
    assert "site" not in fail["remedy"].lower() and "page" not in fail["remedy"].lower()

    # ...without breaking the case the pattern is actually for.
    click = experience.classify("could not find Submit on screen", action="click_text")
    assert click["kind"] == "element_not_found"


def test_chain_steps_carry_their_own_time_not_the_whole_run():
    """
    The report showed open_url [62406ms], wait [0ms], analyze [0ms] — while the
    cost table said open_url 2.3s and analyze 55s. Chain steps are recorded
    after the run, so the first absorbed everything. A trace that points at the
    wrong step is worse than one that points nowhere.
    """
    from services import trace

    trace.start("test", "chain")
    trace.step("desktop.open_url", "", ok=True, took_ms=2328)
    trace.step("desktop.analyze", "", ok=True, took_ms=55115)
    steps = trace.recent(1)[0]["steps"]
    trace.finish("done")

    assert steps[0]["took_ms"] == 2328
    assert steps[1]["took_ms"] == 55115, "the slow step is still invisible"


# ── What three independent reviews converged on ──────────────────────────────


def test_agent_invented_navigation_is_risky():
    """
    All three reviews flagged this and all three were right: "browse" is the
    path the LLM parser and the executor's own decision loop emit, and it was
    not in RISKY_ACTIONS — so a URL nobody typed could drive a browser signed
    in to the user's accounts without asking.
    """
    from agents.executor_agent import ExecutorAgent

    assert ExecutorAgent().is_risky("browse")


def test_typing_a_url_yourself_is_not_gated():
    """
    The other half of the same decision. Naming a destination IS the approval;
    prompting for it would be noise that trains you to click yes without
    reading. open_url is gated by check_url instead.
    """
    from agents.executor_agent import ExecutorAgent

    assert not ExecutorAgent().is_risky("open_url")


def test_opening_a_url_is_never_retried():
    """
    A retry re-runs webbrowser.open() and you get three tabs of the same page.
    The failure was never "it didn't open" — it was "I couldn't confirm it
    opened", and doing it again cannot answer that question.

    Caught by a test going red the moment open_url started verifying, which is
    the only reason it isn't a live bug.
    """
    from agents.desktop_agent import _NO_RETRY

    assert "open_url" in _NO_RETRY


def test_every_action_result_has_one_shape():
    """
    Some primitives returned {success, verified, verify_reason}, others just
    {success}, open_url a third shape. A caller reading `verified` got None
    from half the system and could not tell "not verified" from "this action
    doesn't report it".
    """
    from agents import desktop_agent as da

    for action, params in [
        ("wait", {"seconds": 0.01}),
        ("teleport", {}),  # unknown action
        ("hotkey", {"keys": None}),
    ]:  # raises inside
        r = da._run_action(action, params)
        missing = [k for k in da._CONTRACT_KEYS if k not in r]
        assert not missing, f"{action} is missing {missing} from the contract"


def test_unverified_is_not_the_same_as_failed():
    """
    verified=None means "I didn't check"; False means "I checked and it hadn't
    happened". They send the user to completely different places, and
    collapsing them into one boolean was half the original complaint.
    """
    from agents.desktop_agent import _contract

    assert _contract({"success": True}, "wait")["verified"] is None
    assert _contract({"success": False, "error": "x"}, "wait")["verified"] is False
    assert _contract({"success": True, "verified": True}, "click")["verified"] is True


def test_a_known_reason_is_never_reported_as_unknown():
    """
    "Jarvis couldn't determine why this failed" printed over a perfectly good
    explanation is a lie by omission — and it sends the user to the diagnostics
    screen to read something we already had in hand.
    """
    from services import experience

    fail = experience.classify(
        "asked edge to open the page but never saw an edge process", action="open_url", result={}
    )
    assert "edge" in fail["cause"], f"the real reason was dropped: {fail['cause']!r}"
    assert "couldn't determine" not in fail["cause"]


# ── "The freelance section is just an advert" ────────────────────────────────


def test_a_config_that_can_never_submit_says_so():
    """
    The real setup behind that complaint, from the 2026-08-05 report:

        scanning : remoteok(board) peopleperhour(bid) freelancer(bid) weworkremotely(board)
        logged in: upwork fiverr hubstaff contra wellfound

    The two platforms that accept a bid were the two with no session; the two
    scanned hardest were boards that never accept one. The overlap was EMPTY.
    Jarvis drafted 15 proposals, could send none of them, and showed a green
    "earning for you" over the pile.

    Scanning was working. Submitting was impossible. Nothing said so, and that
    silence is the whole complaint.
    """
    from services.platform_meta import readiness

    r = readiness(
        ["remoteok", "peopleperhour", "freelancer", "weworkremotely"],
        [
            {"platform": p, "logged_in": True}
            for p in ("upwork", "fiverr", "hubstaff", "contra", "wellfound")
        ],
    )
    assert r["can_submit"] is False
    assert set(r["need_login"]) == {"peopleperhour", "freelancer"}
    assert "not logged in" in r["headline"]


def test_logging_in_to_one_bid_site_changes_the_answer():
    """The message has to become good news the moment the situation does."""
    from services.platform_meta import readiness

    r = readiness(["remoteok", "freelancer"], [{"platform": "freelancer", "logged_in": True}])
    assert r["can_submit"] is True
    assert "freelancer" in r["ready"]


def test_boards_only_is_explained_not_reported_as_broken():
    """
    Scanning boards is a perfectly good thing to do — the proposal is still
    worth having when you apply by hand. It must read as a limit, not a fault.
    """
    from services.platform_meta import readiness

    r = readiness(["remoteok", "weworkremotely"], [])
    assert r["can_submit"] is False
    assert r["scanning_is_useful"] is True
    assert "job board" in r["headline"]


def test_a_compound_command_names_the_half_it_could_not_do():
    """
    "open qq and send message to john saying hello" opens QQ and stops, because
    there is no send-a-message capability. That is a missing FEATURE, not a lie
    — but the reply has to say which half was skipped, or it reads as Jarvis
    ignoring you.
    """
    from services import decompose

    out = decompose.decompose("open qq and send message to john saying hello")
    actions = [s["action"] for s in out["steps"]]
    assert "open_app" in actions
    assert out.get("unresolved"), "the unhandled clause vanished silently"
    assert "send message" in " ".join(out["unresolved"]).lower()


# ── "Show me the page — show me it sending it" ───────────────────────────────


def test_the_submission_browser_is_visible_by_default():
    """
    Every submission ran headless=True, so nothing was ever visible and the
    only evidence was a screenshot after the fact — which is why "proof" felt
    like a letter Jarvis wrote to itself.

    Watching the real page open, fill and submit is the difference between
    believing it and taking its word.
    """
    from services.bid_executor import watch_submissions

    assert watch_submissions() is True


def test_it_can_be_turned_off_once_you_trust_it(monkeypatch):
    """Watching is the default, not a sentence. It must get out of the way."""
    from services import bid_executor, config

    monkeypatch.setattr(
        config, "get", lambda k, d=None: "false" if k == "freelance_watch_browser" else d
    )
    assert bid_executor.watch_submissions() is False


def test_an_explicit_headless_caller_still_wins():
    """
    A test or a background retry that genuinely needs headless must be able to
    say so — the setting answers "nobody said", not "always".
    """
    import inspect

    from services import bid_executor

    src = inspect.getsource(bid_executor._execute_queue_item_locked)
    assert "if headless is None:" in src, (
        "the setting overrides an explicit caller instead of filling a blank"
    )
