"""
Regression tests for command understanding.

Every case here is a sentence that Jarvis got wrong on the user's real machine.
The test names say what the user saw, not what the function returns — when one
of these fails, the failure should tell you which user-visible behaviour broke.
"""
import pytest

from services import decompose, tool_registry


def plan(text: str):
    """(actions, params) for a sentence, through the real entry point."""
    steps = decompose.decompose(text)["steps"]
    return [(s["action"], s.get("params", {})) for s in steps]


def actions(text: str):
    return [a for a, _ in plan(text)]


def typed(text: str):
    return [p.get("text", "") for a, p in plan(text) if a == "type_text"]


# ── "It typed the question instead of answering it" ──────────────────────────

def test_notepad_question_is_answered_not_transcribed():
    """
    "Open notepad tell me about yourself" put the characters `me about
    yourself` into Notepad. Two faults: the pronoun stayed in the text, and a
    question aimed at a text editor was treated as literal input.
    """
    steps = plan("Open notepad tell me about yourself")
    assert not any("me about" in t for t in typed("Open notepad tell me about yourself"))
    assert "compose" in [a for a, _ in steps], (
        f"Notepad cannot answer a question, so Jarvis must — got {[a for a, _ in steps]}"
    )


def test_question_to_a_chat_app_stays_literal():
    """The mirror image: Doubao CAN answer, so the question is for the app."""
    steps = plan("open doubao and ask it how it is")
    assert "compose" not in [a for a, _ in steps]
    assert any(a == "type_text" and "how it is" in p.get("text", "") for a, p in steps)
    assert "press" in [a for a, _ in steps], "typed a question into a chat app and never sent it"


def test_composed_prose_is_not_followed_by_enter():
    """Enter after composed text adds a blank line, or sends an essay to a contact."""
    steps = plan("Open notepad tell me about yourself")
    assert "press" not in [a for a, _ in steps]


def test_type_stays_literal():
    assert typed("open notepad and type hello") == ["hello"]


def test_write_composes():
    assert "compose" in actions("open notepad and write about yourself")


@pytest.mark.parametrize("phrase", ["type exactly hello world", "type the words good morning"])
def test_literal_hints_defeat_composition(phrase):
    """"exactly"/"the words" mean literal, whatever else is in the sentence."""
    assert "compose" not in actions(f"open notepad and {phrase}")


# ── Clause splitting ─────────────────────────────────────────────────────────

def test_comma_is_a_step_boundary():
    """"open notepad, tell me a joke" tried to launch an app by that whole name."""
    app = next((p.get("name_or_path") for a, p in plan("open notepad, tell me a joke")
                if a == "open_app"), None)
    assert app == "notepad"


def test_comma_inside_literal_text_is_not_a_boundary():
    assert typed("open notepad and type hello, world") == ["hello, world"]


def test_and_inside_a_search_query_is_not_a_boundary():
    """"black and decker" is one query, not two steps."""
    steps = plan("search black and decker drills")
    url = next((p.get("url", "") for a, p in steps if a == "open_url"), "")
    assert "decker" in url and "drills" in url


def test_search_stops_at_a_follow_on_verb():
    """
    "search BMW M4 and analyze the page" searched for the literal string
    "BMW M4 and analyze the page" — a results page about a sentence nobody
    wrote.
    """
    steps = plan("open browser and search BMW M4 and analyze the page")
    q = next((p.get("query", "") for a, p in steps if a == "open_url"), "")
    assert q.lower() == "bmw m4", f"query was {q!r}"
    assert "analyze" in [a for a, _ in steps]


def test_three_clauses_stay_in_order():
    a = actions("open notepad, then type hello, then save it")
    assert a.index("open_app") < a.index("type_text") < a.index("hotkey")


def test_unhandled_clause_is_reported_not_dropped():
    """
    Silent partial execution is the worst class of bug here: two clauses parse,
    one doesn't, and the reply says "Done".
    """
    out = decompose.decompose("open notepad and frobnicate the widget")
    assert out.get("unresolved"), "the unparsed half vanished without a word"


# ── App resolution ───────────────────────────────────────────────────────────

def test_check_messages_opens_looks_and_reads():
    """The QQ flow: open, wait, screenshot, analyze — in that order."""
    assert actions("check my qq messages") == [
        "open_app", "wait_for_window", "screenshot", "analyze"
    ]


def test_browser_is_resolved_not_hardcoded():
    """
    "open browser" was hardcoded to chrome, on a machine with no Chrome.
    Whatever it resolves to, it must not be a literal "browser".
    """
    app = next((p.get("name_or_path") or p.get("browser")
                for a, p in plan("open browser and search bmw m4")
                if a in ("open_app", "open_url")), None)
    assert app and app != "browser"


def test_search_url_is_reachable_from_china():
    """Google hangs then goes blank without a VPN; that reads as Jarvis broken."""
    assert "google.com" not in tool_registry.search_url("test")
