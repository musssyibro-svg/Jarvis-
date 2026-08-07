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
import os
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
    # NOTE: "browser" is resolved at RUNTIME by default_browser(), not mapped
    # here. It used to be hardcoded to "chrome", so "open browser and search X"
    # tried to launch Chrome on a machine that doesn't have Chrome installed.
    "googlechrome": "chrome", "msedge": "edge",
    "weixin": "wechat", "task manager": "taskmanager", "notepad++": "notepad",
}

# ── Which browser, and which search engine ───────────────────────────────────

_BROWSER_CACHE = {"at": 0.0, "name": None}


def default_browser() -> str:
    """
    The browser actually on this machine.

    Now a thin wrapper over services/providers.py, which does this for EVERY
    capability rather than special-casing browsers. Jarvis thinks in terms of
    "search the web", not "run chrome.exe" — so it adapts to whatever is
    installed instead of expecting the machine to match the code.
    """
    try:
        from services import providers
        return providers.provider_for("web_search") or "edge"
    except Exception:
        return "edge"


def search_url(query: str) -> str:
    """
    A search URL that actually loads from where the user is.

    Google is unreachable from mainland China without a VPN, so sending a
    search there produces a hang and then a blank page — Jarvis looks broken
    when the network is the problem. Bing's China endpoint works without one.
    Configurable, because this is a preference, not a fact.
    """
    from urllib.parse import quote_plus
    q = quote_plus((query or "").strip())
    try:
        from services import config
        engine = (config.get("search_engine", "") or "").strip().lower()
    except Exception:
        engine = ""
    if not engine:
        engine = "bing-cn" if (os.getenv("JARVIS_CN", "1") == "1") else "google"
    return {
        "google": f"https://www.google.com/search?q={q}",
        "bing":   f"https://www.bing.com/search?q={q}",
        "bing-cn": f"https://cn.bing.com/search?q={q}",
        "baidu":  f"https://www.baidu.com/s?wd={q}",
        "duckduckgo": f"https://duckduckgo.com/?q={q}",
    }.get(engine, f"https://cn.bing.com/search?q={q}")


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


# Apps that can ANSWER a question typed into them. Everything else is a place
# to put text, not something to have a conversation with.
#
# This distinction decides who answers "open notepad tell me about yourself".
# Doubao can answer it; Notepad cannot. Typing the question into Notepad and
# calling it done is a fake success — the user gets a text file containing a
# question nobody will ever read.
_CONVERSATIONAL_APPS = {
    "doubao", "kimi", "qq", "wechat", "tim", "dingtalk", "telegram", "whatsapp",
    "discord", "slack", "signal", "line", "skype", "chatgpt", "claude",
}


def _app_can_answer(app: str) -> bool:
    return _canon_app(app) in _CONVERSATIONAL_APPS


def _wants_composition(verb: str, text: str, app: str = "") -> bool:
    """
    Should Jarvis GENERATE this text, or type it as given?

    Getting this wrong is bad in both directions, so the rule is deliberately
    conservative: `type` is always literal, and `write` is only generative when
    the phrasing clearly asks for composed prose. "write hello" still types
    hello. When in doubt, type literally — a wrong literal is obvious and
    harmless, whereas wrongly generating replaces what the user actually wanted
    to say with an invention.

    ONE exception, added because of a real report: "Open notepad tell me about
    yourself" put the characters `me about yourself` in Notepad. Asking a text
    editor a question can only ever mean "you answer it, and write the answer
    here" — there is nothing in Notepad to ask. So ask/tell aimed at a
    non-conversational app composes. Aimed at Doubao or QQ it stays literal,
    because there the question is meant for the app.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    if any(h in t for h in _LITERAL_HINTS):
        return False
    if verb.startswith(("ask", "tell")):
        return bool(app) and not _app_can_answer(app)
    if not verb.startswith(("write", "compose")):
        return False          # type/say/send are never generative
    if any(h in t for h in _COMPOSE_HINTS):
        return True
    # A long phrase after "write" reads as a description of what to write
    # ("write a short introduction for my portfolio site"), not as the text.
    return len(t.split()) >= 5


# Words people put in front of an app name that are not part of it.
#
# "open new notepad" searched the Start Menu for the literal string "new
# notepad" and found nothing — a command that plainly means "open notepad"
# failing for a reason no user could guess. Same for "open a calculator" and
# "open another chrome". These are how people actually talk, and every one of
# them was a hard failure.
#
# Only stripped when something REMAINS, so an app genuinely called "new" is
# still reachable, and only from the front, so "notepad new" is untouched.
_QUALIFIERS = ("new", "another", "a", "an", "the", "my", "some", "up")


def _strip_qualifiers(word: str) -> str:
    parts = (word or "").strip().lower().split()
    while len(parts) > 1 and parts[0] in _QUALIFIERS:
        parts.pop(0)
    return " ".join(parts)


def _canon_app(word: str) -> str:
    w = _strip_qualifiers(word)
    if w == "browser":
        return default_browser()      # what's installed, not what we assumed
    return _APP_ALIASES.get(w, w)


# Words that end a search query and begin a NEW instruction.
#
# "search BMW M4 and analyze the page" is TWO steps. Searching the literal
# string "BMW M4 and analyze the page" is what Jarvis did, and it's worse than
# useless — it produces a page of results about a sentence nobody wrote. The
# query stops at the first of these; everything after is a separate step.
_FOLLOW_ON = (
    "and analyz", "then analyz", "and analys", "then analys",
    "and read", "then read", "and screenshot", "then screenshot",
    "and take a screenshot", "then take a screenshot",
    "and summar", "then summar", "and tell me", "then tell me",
    "and check", "then check", "and show me", "then show me",
    "and describe", "then describe", "and open", "then open",
    "and click", "then click", "and save", "then save",
)


def split_query(text: str):
    """
    Split "<query> and <do something else>" into (query, follow_on_verb|None).

    Deliberately literal rather than model-driven: this runs on every command
    and has to be instant and predictable. A model that occasionally decides
    "BMW M4 and analyze the page" is all one query is exactly the failure being
    fixed here.
    """
    low = (text or "").strip()
    if not low:
        return "", None
    lowered = low.lower()
    cut = None
    for marker in _FOLLOW_ON:
        i = lowered.find(marker)
        # Require at least a couple of words before the marker, so "and" inside
        # a genuine query ("black and decker") isn't treated as a step break.
        if i > 6 and (cut is None or i < cut):
            cut = i
    if cut is None:
        return low.strip(" ,.;"), None
    query = low[:cut].strip(" ,.;")
    rest = lowered[cut:]
    if "screenshot" in rest:
        follow = "screenshot"
    elif any(w in rest for w in ("analyz", "analys", "describe", "tell me",
                                 "summar", "read", "show me", "check")):
        follow = "analyze"
    else:
        follow = None
    return query, follow


# "send a message to john saying hi", "message ahmed on wechat: on my way",
# "dm sara, running late", "text 王伟 saying 好的".
#
# The optional filler between the verb and the name is why this is one regex
# rather than four: people say "send a message to X", "send X a message",
# "send message to X" and "message X" interchangeably, and every one of those
# used to be a different outcome — two parsed, one typed the whole sentence
# into the chat window, and one fell through to the LLM.
_MESSAGE_RE = re.compile(
    r"^\s*(?:send|message|msg|text|dm)\s+"
    r"(?:(?:an?)\s+)?(?:message|msg|text|dm|note)?\s*(?:to\s+)?"
    r"([\w][\w .一-鿿-]{0,40}?)\s*"
    r"(?:\s+(?:on|in|via|using)\s+([\w+]+))?"
    r"\s*(?:saying|that says|:|,)\s*[\"'“]?(.+?)[\"'”]?\s*$")


def message_steps(clause: str, app_hint: str = "") -> list[dict] | None:
    """
    Turn "message <who> on <app>: <what>" into a plan, or return None.

    Resolves the APP by capability when none is named: on this machine that
    means QQ or WeChat, not whatever a generic assistant would assume.

    One step, not five, and that is the point. This used to be click_text(who)
    — OCR, pick the rectangle that most resembles the name — then type_text,
    then press Enter. Nothing between the guess and the send. If the OCR picked
    the wrong row, a real message reached a real person and the reply said
    "Done ✓".

    `send_message` finds the contact as a NAMED ELEMENT, refuses when two
    different names match, confirms the chat actually opened, reads the input
    box back to check the text landed, and stops before Enter unless sending
    was approved. Splitting that across separate steps would let a chain carry
    on past a step that only half-worked, which is exactly what happened.
    """
    mm = _MESSAGE_RE.match(clause or "")
    if not mm:
        return None
    who, app_named, body = (mm.group(1).strip(), (mm.group(2) or "").strip(),
                            mm.group(3).strip())
    # "send Ahmed a message ..." — the name is Ahmed, not "Ahmed a message".
    # The capture swallows the filler, and clicking the wrong contact means
    # sending a real message to the wrong person.
    who = re.sub(r"\s+(?:an?\s+)?(?:message|msg|text|dm|note)$", "", who,
                 flags=re.IGNORECASE).strip()
    if not who or not body:
        return None
    app = _canon_app(app_named) if app_named else (_canon_app(app_hint) if app_hint
                                                   else "")
    if not app:
        try:
            from services import providers
            app = providers.provider_for("message")
        except Exception:
            app = None
    if not app:
        return None
    return [
        {"action": "open_app",        "params": {"name_or_path": app}},
        {"action": "wait_for_window", "params": {"title": app, "timeout": 15}},
        {"action": "send_message",    "params": {
            "app": app, "contact": who, "text": body,
            "compose": _wants_composition("write", body)}},
    ]


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
    # Open the app, then READ IT. This used to be screenshot + ask a vision
    # model — 55 seconds on this machine, measured, for a paraphrase of a
    # picture. read_messages asks Windows for the window's actual text and only
    # falls back to looking at the screen when the app exposes nothing, saying
    # which of the two answered.
    app = _find_app(low)
    wants_messages = (any(w in low for w in _CHECK_WORDS)
                      and any(w in low for w in _MESSAGE_WORDS))
    if app and wants_messages:
        return [
            {"action": "open_app",        "params": {"name_or_path": app}},
            {"action": "wait_for_window", "params": {"title": app, "timeout": 12}},
            {"action": "read_messages",   "params": {
                "app": app,
                "question": f"What new or unread messages are visible in {app}? "
                            f"List each sender and a one-line summary. If none are "
                            f"visible, say so."}},
        ]

    # ── "message <who> on <app>: <text>" / "send <who> a message" ─────────────
    if steps := message_steps(low):
        return steps

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
        # "ask it how..." -> "how...", "tell me about..." -> "about...".
        # Only "it" was stripped before, so "tell me about yourself" kept the
        # "me" and Notepad received the characters `me about yourself`.
        text = re.sub(r"^(?:it|me|us|him|her|them)\s+", "", text).strip() or text

        # "open qq and send message to john saying hello" is a MESSAGE, not a
        # typing job. Reaching this branch first is how it became
        # type_text("message to john saying hello") straight into the QQ window
        # — the whole sentence typed at whoever's chat was already open, and
        # then Enter. Re-parsing the clause here routes it to the verified path
        # instead; if it doesn't parse as a message, the literal typing below
        # still applies, so "open notepad and write X" is untouched.
        if verb in ("send", "message"):
            if msg := message_steps(f"{verb} {text}", app_hint=app):
                return msg

        # ── Browser + search is its own thing ─────────────────────────────────
        # Typing into a browser window is the fragile way to search: it depends
        # on where focus lands and whether the address bar is selected. Going
        # straight to a search URL always works, and it lets a follow-on step
        # ("...and analyze the page") run against the loaded results.
        if verb.startswith("search") and app in ("edge", "chrome", "firefox", "browser"):
            query, follow = split_query(text)
            steps = [{"action": "open_url", "params": {"url": search_url(query),
                                                       "browser": app,
                                                       "query": query}}]
            if follow == "screenshot":
                steps.append({"action": "screenshot", "params": {}})
            elif follow == "analyze":
                steps += [
                    {"action": "wait", "params": {"seconds": 2}},
                    {"action": "analyze", "params": {
                        "prompt": f"These are search results for '{query}'. "
                                  f"Summarise what they say about it."}},
                ]
            return steps

        # TYPE vs WRITE. "type hello" means put those five characters on screen.
        # "write about yourself" means produce a piece of writing — and Jarvis
        # used to type the literal words "about yourself", which is the single
        # most obviously stupid thing it did. `compose` generates the text with
        # the LLM first, then types the result.
        composing = _wants_composition(verb, text, app)
        body = ({"action": "compose",   "params": {"prompt": text, "topic": text}}
                if composing
                else {"action": "type_text", "params": {"text": text}})
        steps = [
            {"action": "open_app",        "params": {"name_or_path": app}},
            {"action": "wait_for_window", "params": {"title": app, "timeout": 12}},
            body,
        ]
        # Press Enter only when the text is a message TO something that will
        # answer it. Composed prose is the answer — hitting Enter after it just
        # adds a blank line to the user's document, and in a chat app it would
        # send Jarvis's own essay to a contact.
        if not verb.startswith(("type", "write")) and not composing:
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
