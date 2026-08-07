"""
services/conversation.py — what the last turn was about.

THE GAP THIS FILLS. Every chat message was parsed in complete isolation, so a
perfectly ordinary exchange fell apart:

    you:     open notepad
    Jarvis:  Done ✓
    you:     type hello there
    Jarvis:  (types into whatever window happens to be in front)

    you:     open qq
    you:     close it
    Jarvis:  "Could not find 'it'"

    you:     open notepad and write about yourself
    you:     do it again
    Jarvis:  "Could not find 'it again'"

Jarvis already has three kinds of memory and NONE of them covers this:

    persona.py       durable facts about you ("I'm a freelance developer")
    brain_service    retrievable knowledge (RAG over notes and documents)
    world_model      what is true on the machine right now

What was missing is the short, disposable thing in between: what WE were just
talking about. That is what this holds, and only that.

DELIBERATELY SMALL AND DELIBERATELY FORGETFUL. In memory, not SQLite — this is
worthless after a restart, and persisting it would mean "close it" could resolve
to an app you opened yesterday, which is worse than not understanding at all.
It also expires: after TTL seconds, "it" means nothing again, because a pronoun
pointing at a twenty-minute-old app is a wrong answer delivered confidently.
"""
from __future__ import annotations

import threading
import time

# How long a pronoun stays meaningful. Short on purpose: resolving "it" to
# something from half an hour ago produces a confident wrong action, which is
# the failure mode this project cares most about.
TTL_SECONDS = 300.0

_lock = threading.Lock()
_sessions: dict[str, dict] = {}


def _blank() -> dict:
    return {"at": 0.0, "message": "", "app": None, "steps": [],
            "ok": None, "reply": ""}


def remember(session_id: str, message: str, steps: list | None = None,
             ok: bool | None = None, reply: str = "") -> None:
    """Record what this turn did. Called after a command runs, never before."""
    # Two shapes arrive here and both must work:
    #   PLAN steps   {"action": "open_app", "params": {"name_or_path": "qq"}}
    #   RESULT steps {"action": "open_app", "app": "qq", "verified": True, ...}
    # Reading only one of them is how this would appear to work in tests and
    # do nothing in the running system.
    app = None
    for s in (steps or []):
        if (s or {}).get("action") not in ("open_app", "focus_window"):
            continue
        p = (s or {}).get("params") or {}
        app = (p.get("name_or_path") or p.get("app") or p.get("title")
               or s.get("name_or_path") or s.get("app") or s.get("title") or app)
    with _lock:
        prev = _sessions.get(session_id) or _blank()
        _sessions[session_id] = {
            "at": time.time(),
            "message": (message or "").strip(),
            # An app from THIS turn wins; otherwise the previous one carries
            # forward, so "open notepad" then "type hi" then "save it" all
            # still refer to notepad.
            "app": app or prev.get("app"),
            "steps": list(steps or []),
            "ok": ok,
            "reply": (reply or "")[:400],
        }


def recall(session_id: str) -> dict:
    """The last turn, or a blank one if there isn't a fresh one."""
    with _lock:
        s = _sessions.get(session_id)
    if not s or (time.time() - s["at"]) > TTL_SECONDS:
        return _blank()
    return dict(s)


def forget(session_id: str = "") -> None:
    with _lock:
        if session_id:
            _sessions.pop(session_id, None)
        else:
            _sessions.clear()


# ── Understanding a follow-up ────────────────────────────────────────────────

# "do it again", "same thing", "once more" — repeat the previous command.
_REPEAT = ("do it again", "do that again", "again please", "same again",
           "same thing", "once more", "one more time", "repeat that",
           "repeat it", "try again", "again")

# A message that is ONLY a pronoun phrase can't be understood alone.
_PRONOUNS = ("it", "that", "this", "them", "there", "the app", "the window")


def is_repeat(message: str) -> bool:
    """Is this asking to run the last command again, and nothing else?"""
    m = " ".join((message or "").lower().split()).strip(" .!?")
    return m in _REPEAT


def resolve(session_id: str, message: str) -> dict:
    """
    Turn a follow-up into something that can stand on its own.

    Returns {text, changed, why}. `text` is the message to actually run — the
    original when nothing needed resolving.

    Only rewrites when there is a FRESH previous turn to point at. With no
    context, "close it" stays "close it" and fails with an honest "I don't know
    what 'it' refers to" — which is far better than guessing at an app and
    closing the wrong one.
    """
    text = (message or "").strip()
    if not text:
        return {"text": text, "changed": False, "why": ""}

    last = recall(session_id)

    if is_repeat(text):
        if last["message"]:
            return {"text": last["message"], "changed": True,
                    "why": f"repeating “{last['message']}”"}
        return {"text": text, "changed": False,
                "why": "nothing to repeat — I don't have a recent command"}

    app = last.get("app")
    if not app:
        return {"text": text, "changed": False, "why": ""}

    low = text.lower()
    words = low.split()

    # "close it" / "close that window" -> "close notepad"
    if words and words[0] in ("close", "quit", "exit") and len(words) <= 3:
        if any(p in low for p in _PRONOUNS) or len(words) == 1:
            return {"text": f"close {app}", "changed": True,
                    "why": f"“{text}” → {app} (the app from the last command)"}

    # A bare instruction with no app named inherits the one we were just in:
    # "type hello", "save it", "press enter", "what's in there".
    INHERITS = ("type ", "write ", "save", "press ", "hit ", "click ",
                "scroll", "read it", "check it", "look at it", "what's in it",
                "whats in it", "what's in there", "send it")
    if any(low.startswith(v) or low == v.strip() for v in INHERITS):
        # Only when no app is named already — "type hello in word" is explicit.
        try:
            from services.tool_registry import KNOWN_APPS
            if not any(a in words for a in KNOWN_APPS):
                # "open <app> and <instruction>", NOT "<instruction> in <app>".
                #
                # The suffix form is a trap: decompose reads "type hello in qq"
                # as typing the literal characters "hello in qq". It also emits
                # no focus step, so the text lands in whatever window is in
                # front — the exact bug this whole batch is about.
                #
                # The prefix form goes down the path that is already correct:
                # open_app on a running app focuses it and verifies, the
                # executor records it as the target, and the keystrokes are
                # aimed at a window we confirmed.
                return {"text": f"open {app} and {text}", "changed": True,
                        "why": f"assuming you still mean {app}"}
        except Exception:
            pass

    return {"text": text, "changed": False, "why": ""}


def prompt_block(session_id: str) -> str:
    """
    A line of context for the model, when a message falls through to plain chat.

    Kept to one line on purpose: this goes into every prompt on a 16 GB machine,
    where context is the thing that decides whether a model fits in RAM.
    """
    last = recall(session_id)
    if not last["message"]:
        return ""
    bits = [f'Your last instruction was: "{last["message"]}"']
    if last.get("app"):
        bits.append(f"in {last['app']}")
    if last.get("ok") is False:
        bits.append("(it failed)")
    return " ".join(bits)


def status() -> dict:
    with _lock:
        return {"sessions": len(_sessions),
                "ttl_seconds": TTL_SECONDS,
                "tracked": [{"session": k, "app": v.get("app"),
                             "age_s": round(time.time() - v["at"], 1)}
                            for k, v in _sessions.items()]}
