"""
What breaks if the UI-reading tier is wrong, described as the user would see it.

Every test here runs against a FAKE accessibility tree. That is not a
compromise — the parts that decide who gets a message are the matching, the
bounding and the verification logic, and none of those need Windows to be
wrong. What genuinely cannot be tested here is whether `uiautomation` returns
the tree we expect from a real WeChat window; that is a live check on the
user's machine and is documented as unverified rather than implied to be
covered.
"""

from collections import namedtuple

import pytest

from agents import ui_agent

Rect = namedtuple("Rect", "left top right bottom")


class _Value:
    def __init__(self, v):
        self.Value = v


class Ctrl:
    """A stand-in for a uiautomation control — only the surface ui_agent uses."""

    def __init__(
        self,
        name="",
        role="Pane",
        value=None,
        rect=(0, 0, 100, 20),
        enabled=True,
        offscreen=False,
        selected=False,
        children=(),
    ):
        self.Name = name
        self.ControlTypeName = role if role.endswith("Control") else role + "Control"
        self.BoundingRectangle = Rect(*rect)
        self.IsEnabled = enabled
        self.IsOffscreen = offscreen
        self._value = value
        self._selected = selected
        self._kids = list(children)
        self.clicked = 0
        self.focused = 0

    def GetChildren(self):
        return list(self._kids)

    def GetValuePattern(self):
        return None if self._value is None else _Value(self._value)

    def GetSelectionItemPattern(self):
        return _Sel(self._selected)

    def Click(self, **kw):
        self.clicked += 1

    def SetFocus(self):
        self.focused += 1


class _Sel:
    def __init__(self, v):
        self.IsSelected = v


def chat_window(contacts=("Ahmed", "Ahmed Group"), messages=(("Ahmed", "hi"),)):
    """A window shaped like every desktop chat app: contact list, message list,
    compose box at the bottom."""
    contact_items = [
        Ctrl(c, "ListItem", rect=(0, 60 + i * 40, 240, 100 + i * 40))
        for i, c in enumerate(contacts)
    ]
    msg_items = []
    for i, (who, what) in enumerate(messages):
        msg_items.append(
            Ctrl(
                "",
                "ListItem",
                rect=(260, 60 + i * 50, 900, 105 + i * 50),
                children=[Ctrl(who, "Text"), Ctrl(what, "Text")],
            )
        )
    return Ctrl(
        "WeChat",
        "Window",
        rect=(0, 0, 900, 700),
        children=[
            Ctrl("", "List", rect=(0, 50, 240, 700), children=contact_items),
            Ctrl("", "List", rect=(260, 50, 900, 560), children=msg_items),
            Ctrl("", "Edit", value="", rect=(260, 580, 900, 660)),
        ],
    )


def nodes_of(root):
    nodes, cut = ui_agent.walk(root)
    return nodes, cut


# ── Reading ──────────────────────────────────────────────────────────────────


def test_checking_messages_returns_what_they_actually_say():
    """The old path screenshotted the window and asked a vision model what it
    saw. If this breaks, "check my messages" goes back to a 55-second paraphrase
    of a JPEG."""
    nodes, _ = nodes_of(chat_window(messages=[("Ahmed", "are we still on for 6"), ("You", "yes")]))
    containers = ui_agent.text_containers(nodes)
    assert containers, "the message list was not recognised as a list"
    rows = ui_agent._items_of(nodes, containers[0][0])
    texts = [ui_agent._row_text(nodes, r) for r in rows]
    assert any("are we still on for 6" in t for t in texts)


def test_a_quiet_chat_does_not_return_your_contact_list_as_messages():
    """
    Forty contacts and three messages: the sidebar holds more TEXT than the
    conversation does. Ranking by text volume made "check my messages" answer
    with a list of your friends' names — plausible, confident, and not what was
    asked. The conversation pane is the big one on screen; that's the signal.
    """
    root = chat_window(
        contacts=tuple(f"Contact {i} with a fairly long display name" for i in range(40)),
        messages=[("Ahmed", "ok"), ("You", "yes"), ("Ahmed", "see you")],
    )
    nodes, _ = nodes_of(root)
    container, _ = ui_agent.text_containers(nodes)[0]
    rows = ui_agent._items_of(nodes, container)
    texts = " ".join(ui_agent._row_text(nodes, r) for r in rows)
    assert "see you" in texts
    assert "Contact 0" not in texts


def test_an_enclosing_web_view_does_not_win_on_size_alone():
    """A document wrapping the whole window is bigger than every list in it. If
    it wins, every 'message' is the entire page pasted together."""
    inner = Ctrl(
        "",
        "List",
        rect=(0, 100, 400, 500),
        children=[Ctrl("real row", "ListItem", rect=(0, 100, 400, 140))],
    )
    root = Ctrl(
        "App",
        "Window",
        rect=(0, 0, 900, 700),
        children=[Ctrl("", "Document", rect=(0, 0, 900, 700), children=[inner])],
    )
    nodes, _ = nodes_of(root)
    container, _ = ui_agent.text_containers(nodes)[0]
    assert container.role == "list"


def test_one_message_with_nested_text_is_not_counted_as_three():
    """A bubble is a list item holding a sender node and a text node. Flattening
    every descendant turned one message into several and made an inbox look
    busier than it is."""
    nodes, _ = nodes_of(chat_window(messages=[("Ahmed", "hi"), ("You", "hello")]))
    container = ui_agent.text_containers(nodes)[0][0]
    rows = ui_agent._items_of(nodes, container)
    assert len(rows) == 2


def test_an_app_that_shows_nothing_is_not_reported_as_an_empty_inbox(monkeypatch):
    """QQ NT draws its chat on a canvas and exposes no text. Saying "no new
    messages" on that basis is a lie about the world; saying "I couldn't read
    it" is a fact about the read."""
    blank = Ctrl(
        "QQ", "Window", rect=(0, 0, 800, 600), children=[Ctrl("", "Pane"), Ctrl("", "Pane")]
    )
    monkeypatch.setattr(
        ui_agent,
        "_read_nodes",
        lambda app, *a, **k: {"ok": True, "nodes": nodes_of(blank)[0], "cut": "", "window": "QQ"},
    )
    got = ui_agent.read_messages("qq")
    assert got["messages"] == []
    assert got["verified"] is False
    assert "will not claim" in got["error"]


def test_a_window_too_big_to_read_says_it_was_cut_short():
    """Silently returning the first N elements and then answering "nothing
    there" is the same false negative wearing a bound."""
    kids = [Ctrl(f"row {i}", "ListItem") for i in range(50)]
    root = Ctrl("big", "Window", children=[Ctrl("", "List", children=kids)])
    nodes, cut = ui_agent.walk(root, max_nodes=10)
    assert len(nodes) == 10
    assert "stopped after 10 elements" in cut


def test_a_deeply_nested_window_stops_instead_of_running_forever():
    """A web view can nest arbitrarily. Without a depth cap the walk is bounded
    only by the app's imagination."""
    node = Ctrl("deep", "Pane")
    for _ in range(80):
        node = Ctrl("wrap", "Pane", children=[node])
    nodes, _ = ui_agent.walk(node, max_depth=5)
    assert max(n.depth for n in nodes) <= 5


# ── Choosing who to talk to ──────────────────────────────────────────────────


def test_an_exact_name_beats_a_longer_one_that_contains_it():
    """ "Ahmed" and "Ahmed Group" are different chats. Picking the wrong one
    sends a private message to a group."""
    nodes, _ = nodes_of(chat_window(contacts=("Ahmed Group", "Ahmed")))
    got = ui_agent.match(nodes, "Ahmed", role="listitem")
    assert got["found"]
    assert got["node"].name == "Ahmed"


def test_two_different_people_matching_equally_stops_instead_of_guessing():
    """This is the failure the tier exists to prevent: a message to the wrong
    person, reported as sent."""
    nodes, _ = nodes_of(chat_window(contacts=("Ahmed Ali", "Ahmed Bakr")))
    got = ui_agent.match(nodes, "Ahmed", role="listitem")
    assert not got["found"]
    assert got["ambiguous"] is True
    assert "Ahmed Ali" in got["reason"] and "Ahmed Bakr" in got["reason"]


def test_the_same_person_listed_twice_is_not_treated_as_ambiguous():
    """A contact appears in the list and again as the conversation header.
    Refusing there would make the feature useless."""
    root = Ctrl(
        "WeChat",
        "Window",
        children=[
            Ctrl("Ahmed", "Text", rect=(300, 0, 600, 40)),  # header
            Ctrl("", "List", children=[Ctrl("Ahmed", "ListItem", rect=(0, 60, 240, 100))]),
        ],
    )
    nodes, _ = nodes_of(root)
    got = ui_agent.match(nodes, "Ahmed")
    assert got["found"]
    assert got["node"].role == "listitem", "should prefer the clickable one"


def test_a_name_typed_on_a_chinese_keyboard_still_matches():
    """A Chinese IME produces full-width Latin letters. "Ａｈｍｅｄ" and "Ahmed"
    are different strings and the same person; without NFKC the contact is
    simply never found."""
    nodes, _ = nodes_of(chat_window(contacts=("Ａｈｍｅｄ",)))
    assert ui_agent.match(nodes, "ahmed", role="listitem")["found"]


def test_a_name_that_is_not_there_says_so_rather_than_clicking_the_closest():
    nodes, _ = nodes_of(chat_window(contacts=("Ahmed", "Sara")))
    got = ui_agent.match(nodes, "Mohammed", role="listitem")
    assert not got["found"]
    assert not got.get("ambiguous")


# ── Where the typing goes ────────────────────────────────────────────────────


def test_typing_targets_the_compose_box_not_the_search_box():
    """Every chat app puts search at the top and compose at the bottom. Typing
    a message into search is silent — nothing is sent and nothing complains."""
    root = Ctrl(
        "WeChat",
        "Window",
        rect=(0, 0, 900, 700),
        children=[
            Ctrl("Search", "Edit", value="", rect=(0, 0, 240, 40)),
            Ctrl("", "Edit", value="", rect=(260, 580, 900, 660)),
        ],
    )
    nodes, _ = nodes_of(root)
    picked = ui_agent._pick_field(nodes, "")
    assert not isinstance(picked, dict)
    assert picked.rect[1] == 580


def test_a_window_with_nowhere_to_type_says_so():
    nodes, _ = nodes_of(Ctrl("Viewer", "Window", children=[Ctrl("hello", "Text")]))
    got = ui_agent._pick_field(nodes, "")
    assert isinstance(got, dict) and got["success"] is False
    assert "no text field" in got["error"]


# ── The approval gate ────────────────────────────────────────────────────────


@pytest.fixture
def _pretend_windows(monkeypatch):
    monkeypatch.setattr(ui_agent, "_load", lambda: True)
    monkeypatch.setattr(ui_agent, "_input_allowed", lambda: "")


def test_nothing_is_sent_until_it_is_approved(_pretend_windows, monkeypatch):
    """The message must sit visibly in the real input box, unsent, so the user
    can see what would go out before it does."""
    monkeypatch.setattr(
        ui_agent,
        "click",
        lambda app, name, role="": {"success": True, "verified": True, "clicked": name},
    )
    monkeypatch.setattr(
        ui_agent,
        "type_into",
        lambda app, f, t, submit=False: {
            "success": True,
            "verified": True,
            "field": "compose",
            "field_value": t,
        },
    )
    pressed = []
    monkeypatch.setattr(
        "agents.desktop_agent.press", lambda k: pressed.append(k) or {"success": True}
    )

    got = ui_agent.send_message("wechat", "Ahmed", "on my way", send=False)
    assert got["success"] and got["sent"] is False
    assert got["awaiting_approval"] is True
    assert got["composed"]["message"] == "on my way"
    assert pressed == [], "Enter was pressed without approval"


def test_a_click_that_changed_nothing_stops_before_anything_is_typed(_pretend_windows, monkeypatch):
    """If Jarvis cannot tell whose chat is open, typing into it is how a message
    reaches the wrong person. The chain has to stop at the click."""
    monkeypatch.setattr(
        ui_agent,
        "click",
        lambda app, name, role="": {"success": True, "verified": False, "clicked": name},
    )
    typed = []
    monkeypatch.setattr(ui_agent, "type_into", lambda *a, **k: typed.append(a) or {"success": True})

    got = ui_agent.send_message("wechat", "Ahmed", "on my way", send=False)
    assert got["success"] is False
    assert "can't tell whose chat is open" in got["error"]
    assert typed == [], "typed into a chat it could not identify"


def test_text_that_did_not_land_in_the_box_is_never_submitted(_pretend_windows, monkeypatch):
    monkeypatch.setattr(
        ui_agent, "click", lambda app, name, role="": {"success": True, "verified": True}
    )
    monkeypatch.setattr(
        ui_agent,
        "type_into",
        lambda app, f, t, submit=False: {
            "success": True,
            "verified": False,
            "field": "compose",
            "field_value": "",
            "verify_reason": "the field is now empty",
        },
    )
    pressed = []
    monkeypatch.setattr(
        "agents.desktop_agent.press", lambda k: pressed.append(k) or {"success": True}
    )

    got = ui_agent.send_message("wechat", "Ahmed", "on my way", send=True)
    assert got["success"] is False
    assert pressed == []


def test_a_send_that_cannot_be_confirmed_says_so_and_refuses_to_retry(
    _pretend_windows, monkeypatch
):
    """Retrying an unconfirmed send is how someone receives the same message
    twice. The honest answer is "I can't tell", not another Enter."""
    monkeypatch.setattr(
        ui_agent, "click", lambda app, name, role="": {"success": True, "verified": True}
    )
    monkeypatch.setattr(
        ui_agent,
        "type_into",
        lambda app, f, t, submit=False: {
            "success": True,
            "verified": True,
            "field": "compose",
            "field_value": t,
        },
    )
    monkeypatch.setattr("agents.desktop_agent.press", lambda k: {"success": True})
    monkeypatch.setattr(
        ui_agent, "read_messages", lambda app, limit=30: {"success": True, "messages": []}
    )
    monkeypatch.setattr(ui_agent, "_field_value", lambda app: None)

    got = ui_agent.send_message("wechat", "Ahmed", "on my way", send=True)
    assert got["sent"] is True
    assert got["verified"] is False
    assert "assume it did NOT send" in got["verify_reason"]
    assert "will not retry" in got["what_to_do"]


def test_the_emergency_stop_covers_this_route_too(monkeypatch):
    """UI Automation moves the same mouse. Reaching the desktop through a
    different library must not be a way around the stop button."""
    monkeypatch.setattr("agents.desktop_agent.is_estopped", lambda: True)
    got = ui_agent.send_message("wechat", "Ahmed", "hi", send=True)
    assert got["success"] is False
    assert "EMERGENCY STOP" in got["error"]


# ── Honest degradation ───────────────────────────────────────────────────────


def test_on_a_machine_without_this_it_says_why_and_does_not_crash():
    """CI and this developer container are Linux. Every entry point must return
    a result, never raise, and never tell the user to pip install something
    that would not help."""
    got = ui_agent.available()
    assert set(got) >= {"ok", "reason", "what_to_do"}
    import os

    if os.name != "nt":
        assert got["ok"] is False
        assert "Windows" in got["reason"]
        assert "pip install" not in got["what_to_do"]
        for call in (
            lambda: ui_agent.snapshot("wechat"),
            lambda: ui_agent.read_messages("wechat"),
            lambda: ui_agent.click("wechat", "Ahmed"),
            lambda: ui_agent.type_into("wechat", "", "hi"),
        ):
            res = call()
            assert res["success"] is False
            assert res["error"]
