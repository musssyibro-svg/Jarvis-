"""
services/tool_registry.py — deterministic action shortcuts.

The "qq" screenshot is the reason this exists. Asked to "open qq and check
messages", the planner handed the goal to the LLM, which had never heard of QQ
and hallucinated "Visit a popular messaging platform like Telegram or WhatsApp.
Enter 'qq' in the search bar…". Nonsense — because the system reached for the
LLM before checking whether a concrete tool already existed.

This registry is that missing first stop. Known commands ("open qq", "open
chrome", "check my <app> messages", "screenshot", "type …") resolve DIRECTLY to
executable desktop steps with zero LLM reasoning. Only genuinely novel goals
fall through to the planner's LLM decomposition.

Both the chat commander and the project planner call resolve_steps() first.
Deterministic where we can be, generative only where we must be — the hybrid
pattern that keeps a local assistant fast and predictable.
"""
import re

# Apps Jarvis can launch by name. Superset of desktop_agent.KNOWN plus the
# China-market apps the user actually runs (QQ, WeChat, etc.) — the whole point
# of the qq fix. open_app() already resolves anything installed via the Start
# Menu, so listing here just means "recognise this word as an app to launch".
KNOWN_APPS = {
    "qq", "wechat", "weixin", "tim", "dingtalk", "doubao", "douyin", "kimi",
    "telegram", "whatsapp", "discord", "slack", "signal", "line", "skype",
    "chrome", "googlechrome", "edge", "msedge", "firefox", "browser",
    "notepad", "notepad++", "notes", "calculator", "calc", "explorer",
    "files", "cmd", "terminal", "powershell", "word", "excel", "powerpoint",
    "outlook", "vscode", "code", "steam", "spotify", "paint", "photoshop",
    "settings", "taskmanager", "task manager", "obs", "zoom",
}

# Words that mean "read what's on screen now" after opening something.
_CHECK_WORDS = ("check", "read", "see", "view", "show", "any new", "unread")
_MESSAGE_WORDS = ("message", "messages", "chat", "chats", "inbox", "notification",
                  "notifications", "dm", "dms")

_APP_ALIASES = {
    "browser": "chrome", "googlechrome": "chrome", "msedge": "edge",
    "weixin": "wechat", "task manager": "taskmanager", "notepad++": "notepad",
}


# Phrases that mean "produce writing", not "reproduce these characters".
_COMPOSE_HINTS = (
    "about ", "a story", "a poem", "an essay", "a letter", "an email",
    "yourself", "myself", "an introduction", "a summary", "a bio",
    "a report", "an analysis", "a proposal", "a draft", "a note",
    "a list of", "a plan", "a review", "a paragraph", "a message to",
    "explain ", "describe ", "why ", "how to ",
)
# ...and phrases that mean the literal opposite, whatever else is in the string.
_LITERAL_HINTS = ("exactly", "verbatim", "literally", "the words", "character for character")


def _wants_composition(verb: str, text: str) -> bool:
    """
    Should Jarvis GENERATE this text, or type it as given?

    Getting this wrong is bad in both directions, so the rule is deliberately
    conservative: `type` is always literal, and `write` is only generative when
    the phrasing clearly asks for composed prose. "write hello" still types
    hello. When in doubt, type literally — a wrong literal is obvious and
    harmless, whereas wrongly generating replaces what the user actually wanted
    to say with an invention.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    if any(h in t for h in _LITERAL_HINTS):
        return False
    if not verb.startswith(("write", "compose")):
        return False          # type/say/ask/send are never generative
    if any(h in t for h in _COMPOSE_HINTS):
        return True
    # A long phrase after "write" reads as a description of what to write
    # ("write a short introduction for my portfolio site"), not as the text.
    return len(t.split()) >= 5


def _canon_app(word: str) -> str:
    w = (word or "").strip().lower()
    return _APP_ALIASES.get(w, w)


def _looks_like_known_app(word: str) -> bool:
    w = _canon_app(word)
    return w in KNOWN_APPS or w in {_canon_app(a) for a in KNOWN_APPS}


def resolve_steps(text: str) -> list[dict] | None:
    """
    Turn a known command into concrete desktop steps, or return None so the
    caller falls back to the LLM. Steps use the same schema as
    desktop_agent.execute_chain: {"action": ..., "params": {...}}.
    """
    if not text:
        return None
    m = text.strip()
    low = m.lower()

    # ── "check my <app> messages" / "<app> check messages" / "read <app>" ──────
    # open the app, wait for it, screenshot, and let vision summarise — the exact
    # flow the QQ plan SHOULD have produced.
    app = _find_app(low)
    wants_messages = (any(w in low for w in _CHECK_WORDS)
                      and any(w in low for w in _MESSAGE_WORDS))
    if app and wants_messages:
        return [
            {"action": "open_app",        "params": {"name_or_path": app}},
            {"action": "wait_for_window", "params": {"title": app, "timeout": 12}},
            {"action": "screenshot",      "params": {}},
            {"action": "analyze",         "params": {
                "question": f"What new or unread messages are visible in {app}? "
                            f"List each sender and a one-line summary. If none are "
                            f"visible, say so."}},
        ]

    # ── "open <app> and ask/type/say/search <text>" → open, focus, type, enter ──
    # This is the doubao case: "open doubao and ask it how it is" must actually
    # type the question into the app, not just open it and claim done.
    am = re.match(r"^\s*(?:open|launch|start|run)\s+(?:the\s+|my\s+)?([\w][\w .+&-]*?)\s+"
                  r"(?:and\s+|then\s+)?(ask(?:\s+it)?|tell(?:\s+it)?|say|search(?:\s+for)?|"
                  r"type|write|send|message)\s+[\"'“]?(.+?)[\"'”]?\s*$", low)
    if am and _looks_like_known_app(am.group(1)):
        app = _canon_app(am.group(1))
        verb = am.group(2)
        text = am.group(3).strip()
        text = re.sub(r"^it\s+", "", text).strip() or text   # "ask it how..." -> "how..."

        # TYPE vs WRITE. "type hello" means put those five characters on screen.
        # "write about yourself" means produce a piece of writing — and Jarvis
        # used to type the literal words "about yourself", which is the single
        # most obviously stupid thing it did. `compose` generates the text with
        # the LLM first, then types the result.
        body = ({"action": "compose",   "params": {"prompt": text, "topic": text}}
                if _wants_composition(verb, text)
                else {"action": "type_text", "params": {"text": text}})
        steps = [
            {"action": "open_app",        "params": {"name_or_path": app}},
            {"action": "wait_for_window", "params": {"title": app, "timeout": 12}},
            body,
        ]
        # Press Enter only for send/ask/search verbs (chat & search boxes submit
        # on Enter). For "type/write" into an editor like Notepad, leave it be.
        if not verb.startswith(("type", "write")):
            steps.append({"action": "press", "params": {"key": "enter"}})
        return steps

    # ── plain "open <app>" / "launch <app>" / "start <app>" ────────────────────
    om = re.match(r"^\s*(?:open|launch|start|run|fire up)\s+(?:the\s+|my\s+|up\s+)?"
                  r"([\w][\w .+&-]*?)\s*$", low)
    if om and _looks_like_known_app(om.group(1)):
        return [{"action": "open_app", "params": {"name_or_path": _canon_app(om.group(1))}}]

    # ── "screenshot" / "what's on my screen" ───────────────────────────────────
    if low in ("screenshot", "take a screenshot", "screen shot", "capture screen") \
       or low.startswith(("what's on my screen", "whats on my screen", "read my screen")):
        return [
            {"action": "screenshot", "params": {}},
            {"action": "analyze",    "params": {"question": "Describe what is on the "
                                                "screen and suggest a next action."}},
        ]

    return None


def _find_app(low: str) -> str | None:
    """Find a known app name mentioned anywhere in the text."""
    for word in re.findall(r"[\w+#]+", low):
        if _looks_like_known_app(word):
            return _canon_app(word)
    # multiword ("task manager")
    for app in KNOWN_APPS:
        if " " in app and app in low:
            return _canon_app(app)
    return None


def is_known_command(text: str) -> bool:
    return resolve_steps(text) is not None


def list_tools() -> list[dict]:
    """For the UI: what deterministic shortcuts exist."""
    return [
        {"tool": "open_app",        "example": "open qq",
         "desc": "Launch any installed app directly (no LLM guessing)."},
        {"tool": "check_messages",  "example": "check my qq messages",
         "desc": "Open the app, screenshot it, and summarise unread messages."},
        {"tool": "screenshot",      "example": "what's on my screen",
         "desc": "Capture the screen and describe it."},
        {"tool": "type_text",       "example": "open notepad and type hello",
         "desc": "Chained desktop input with window-wait between steps."},
    ]
