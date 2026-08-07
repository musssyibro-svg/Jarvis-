"""
Follow-up messages used to be parsed in complete isolation.

    you:     open qq
    you:     close it
    Jarvis:  "Could not find 'it'"

    you:     open notepad and write about yourself
    you:     do it again
    Jarvis:  "Could not find 'it again'"

Jarvis already had three kinds of memory — durable facts about you, retrievable
knowledge, and live machine state — and none covered the short disposable thing
in between: what we were just talking about.

The rule that matters most here is what happens with NO context: the pronoun
stays unresolved and fails honestly. Guessing at an app and closing the wrong
one is far worse than saying "I don't know what 'it' means".
"""

import time

import pytest

from services import conversation as cv


@pytest.fixture(autouse=True)
def _clean():
    cv.forget()
    yield
    cv.forget()


def open_app_turn(app, session="s"):
    cv.remember(
        session,
        f"open {app}",
        steps=[{"action": "open_app", "params": {"name_or_path": app}}],
        ok=True,
    )


# ── Resolving a follow-up ────────────────────────────────────────────────────


def test_close_it_means_the_app_we_just_opened():
    open_app_turn("qq")
    out = cv.resolve("s", "close it")
    assert out["changed"] is True
    assert out["text"] == "close qq"


def test_a_bare_instruction_inherits_the_current_app():
    open_app_turn("notepad")
    out = cv.resolve("s", "type hello there")
    assert out["changed"] is True
    assert "notepad" in out["text"]


def test_the_inherited_app_does_not_end_up_in_the_TYPED_TEXT():
    """
    The near-miss that made this test exist. The obvious rewrite is
    "type hello in notepad" — and decompose reads that as typing the literal
    characters "hello in notepad". It also emits no focus step, so the text
    lands in whatever window is in front, which is the bug this whole batch is
    about.

    The prefix form goes down the path that is already correct.
    """
    from services import decompose

    open_app_turn("notepad")
    steps = decompose.decompose(cv.resolve("s", "type hello")["text"])["steps"]
    typed = [s["params"].get("text") for s in steps if s["action"] == "type_text"]
    assert typed == ["hello"], f"the app name leaked into the typed text: {typed}"

    actions = [s["action"] for s in steps]
    assert actions[0] == "open_app", (
        "there must be a step that puts the app in front before typing into it"
    )


def test_an_explicit_app_is_never_overridden():
    """ "type hello in word" means Word, whatever we were just doing."""
    open_app_turn("notepad")
    out = cv.resolve("s", "type hello in word")
    assert out["changed"] is False


def test_do_it_again_repeats_the_last_command():
    cv.remember("s", "open notepad and write about yourself", steps=[], ok=True)
    out = cv.resolve("s", "do it again")
    assert out["text"] == "open notepad and write about yourself"


def test_repeating_a_follow_up_repeats_the_ACTION_not_the_pronoun():
    """
    What gets remembered has to be the RESOLVED text. Remember "close it" and
    "do it again" replays a pronoun that resolves against itself and means
    nothing. handle_chat resolves before it runs and remembers what it ran.
    """
    open_app_turn("qq")
    ran = cv.resolve("s", "close it")["text"]
    assert ran == "close qq"
    cv.remember("s", ran, steps=[{"action": "close_app", "app": "qq"}], ok=True)

    assert cv.resolve("s", "do it again")["text"] == "close qq"


@pytest.mark.parametrize("phrase", ["again", "same thing", "once more", "repeat that"])
def test_the_other_ways_of_saying_again(phrase):
    cv.remember("s", "open calculator", steps=[], ok=True)
    assert cv.resolve("s", phrase)["text"] == "open calculator"


# ── The important half: NOT guessing ─────────────────────────────────────────


def test_with_no_history_a_pronoun_stays_unresolved():
    """
    No context means no guess. "close it" must fail honestly rather than close
    whatever app happens to be lying around.
    """
    out = cv.resolve("fresh-session", "close it")
    assert out["changed"] is False
    assert out["text"] == "close it"


def test_do_it_again_with_nothing_to_repeat_says_so():
    out = cv.resolve("fresh-session", "do it again")
    assert out["changed"] is False
    assert "nothing to repeat" in out["why"]


def test_context_expires():
    """A pronoun pointing at a twenty-minute-old app is a confident wrong answer."""
    open_app_turn("qq")
    cv._sessions["s"]["at"] = time.time() - (cv.TTL_SECONDS + 1)
    assert cv.resolve("s", "close it")["changed"] is False


def test_sessions_do_not_leak_into_each_other():
    open_app_turn("qq", session="a")
    assert cv.resolve("b", "close it")["changed"] is False


def test_a_full_sentence_is_left_alone():
    open_app_turn("notepad")
    for msg in ("open calculator and type 1+1", "what's on my screen", "check my qq messages"):
        assert cv.resolve("s", msg)["changed"] is False, msg


# ── Reading the two step shapes ──────────────────────────────────────────────


def test_remembers_the_app_from_executor_RESULT_steps():
    """
    Result steps carry the action's own return ({"app": "qq"}), not "params".
    Reading only the plan shape would look right in a test and do nothing in
    the running system, because handle_chat passes results.
    """
    cv.remember(
        "s",
        "open qq",
        steps=[{"step": 1, "action": "open_app", "app": "qq", "verified": True}],
        ok=True,
    )
    assert cv.recall("s")["app"] == "qq"


def test_the_app_carries_across_turns_that_dont_name_one():
    """ "open notepad" -> "type hi" -> "save it" all still mean notepad."""
    open_app_turn("notepad")
    cv.remember("s", "type hi", steps=[{"action": "type_text"}], ok=True)
    assert cv.recall("s")["app"] == "notepad"
    assert cv.resolve("s", "close it")["text"] == "close notepad"


def test_prompt_block_is_one_line_and_mentions_the_app():
    """This goes into every prompt on a 16GB machine — it must stay small."""
    open_app_turn("notepad")
    block = cv.prompt_block("s")
    assert "\n" not in block
    assert "notepad" in block


def test_prompt_block_is_empty_with_no_history():
    assert cv.prompt_block("nobody") == ""
