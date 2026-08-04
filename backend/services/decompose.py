"""
services/decompose.py — turn a sentence into an ordered plan.

This fixes the single most visible weakness. Asked to

    "open browser and search BMW M4 and analyze the page"

Jarvis searched for the literal string "BMW M4 and analyze the page" — because
the whole sentence was treated as one command with one object. A person hearing
that sentence hears four things: open a browser, search a term, wait for the
page, describe it. That is what this module produces.

    sentence -> clauses -> intents -> steps

Three properties matter more than cleverness here:

  * IT SPLITS ON VERBS, NOT ON "and". "black and decker drill" is one query;
    "search X and analyze the page" is two clauses. The difference is whether
    the word after the connector is an action verb, not the connector itself.

  * CONTEXT CARRIES FORWARD. "open notepad, then write about yourself" — the
    second clause has no object of its own; it inherits the app the first clause
    opened. Without this, every clause has to restate its target and the plan
    reads like a robot's shopping list.

  * IT IS DETERMINISTIC. This runs on every single command. A model asked to
    decompose "search BMW M4 and analyze the page" gets it right most of the
    time, and the times it doesn't are indistinguishable from the bug being
    fixed. Rules here, model only for clauses no rule understands.

The output is the same step schema desktop_agent.execute_chain already runs, so
nothing downstream changes.
"""
from __future__ import annotations

import re

# Verbs that can START a clause. A connector followed by one of these is a step
# boundary; a connector followed by anything else is part of the current object.
#
# Ordered longest-first at match time so "look up" beats "look".
ACTION_VERBS: dict[str, str] = {
    # launching
    "open": "open", "launch": "open", "start": "open", "run": "open",
    "fire up": "open", "bring up": "open", "pull up": "open",
    # closing
    "close": "close", "quit": "close", "exit": "close", "kill": "close",
    # web
    "search": "search", "search for": "search", "google": "search",
    "look up": "search", "find": "search", "browse": "navigate",
    "go to": "navigate", "navigate to": "navigate", "visit": "navigate",
    # text
    "type": "type", "enter": "type", "input": "type",
    "write": "write", "compose": "write", "draft": "write",
    "say": "type", "tell": "type", "ask": "ask", "reply": "write",
    # input devices
    "click": "click", "tap": "click", "press": "press", "hit": "press",
    "scroll": "scroll", "select": "click",
    # perception
    "screenshot": "screenshot", "take a screenshot": "screenshot",
    "capture": "screenshot",
    "analyze": "analyze", "analyse": "analyze", "read": "analyze",
    "summarize": "analyze", "summarise": "analyze", "describe": "analyze",
    "check": "analyze", "look at": "analyze", "show me": "analyze",
    "tell me about": "analyze", "explain": "analyze",
    # messaging
    "send": "send", "message": "send", "dm": "send", "text": "send",
    # files
    "save": "save", "copy": "copy", "paste": "paste", "delete": "delete",
    "rename": "rename", "download": "download",
    # timing
    "wait": "wait", "pause": "wait",
}

# Longest first — "take a screenshot" must beat "take", "search for" beat "search".
_VERBS_BY_LENGTH = sorted(ACTION_VERBS, key=len, reverse=True)

# Words that join clauses. Only a boundary when an action verb follows.
#
# "," and ";" are in here for the same reason as the words: people write "open
# notepad, tell me a joke" constantly. Without the comma the whole tail became
# the app name and Jarvis tried to launch an application called "notepad, tell
# me a joke". The verb-follows rule is what keeps this safe — "type hello,
# world" has no verb after the comma, so it stays one clause.
_CONNECTORS = ("and then", "then", "and after that", "after that", "and also",
               "also", "and", "next", "afterwards", "followed by", ";", ",")

# Filler between a connector and its verb: "and then please also open ..."
_FILLER = ("please", "just", "now", "also", "go ahead and", "you can", "can you",
           "could you", "i want you to", "i'd like you to")


def _strip_filler(s: str) -> str:
    out = s.strip(" ,.;:")
    changed = True
    while changed:
        changed = False
        low = out.lower()
        for f in _FILLER:
            if low.startswith(f + " "):
                out, changed = out[len(f):].strip(), True
                break
    return out


def _leading_verb(clause: str) -> tuple[str, str, str] | None:
    """
    ("open", "open", "notepad") — the matched word, its canonical intent, and
    whatever follows it. None when the clause doesn't start with an action.
    """
    c = _strip_filler(clause).lower()
    for verb in _VERBS_BY_LENGTH:
        if c == verb:
            return verb, ACTION_VERBS[verb], ""
        if c.startswith(verb + " "):
            return verb, ACTION_VERBS[verb], _strip_filler(clause)[len(verb):].strip()
    return None


def _protect_quotes(text: str) -> tuple[str, dict]:
    """
    Hide quoted spans before splitting.

    `type "open the door and run"` is one literal string, not three clauses.
    Splitting inside a quotation would silently corrupt text the user asked to
    be reproduced exactly.
    """
    store, out, idx = {}, text, 0
    for pattern in (r'"[^"]*"', r"'[^']*'", r"[“][^”]*[”]"):
        def _sub(m):
            nonlocal idx
            key = f"\x00Q{idx}\x00"
            store[key] = m.group(0)
            idx += 1
            return key
        out = re.sub(pattern, _sub, out)
    return out, store


def _restore(text: str, store: dict) -> str:
    for k, v in store.items():
        text = text.replace(k, v)
    return text


def split_clauses(text: str) -> list[str]:
    """
    Break a sentence at real step boundaries.

    A connector only splits when an action verb follows it, which is what keeps
    "black and decker" and "salt and pepper" whole while still separating
    "search X and analyze the page".
    """
    raw = (text or "").strip()
    if not raw:
        return []
    protected, store = _protect_quotes(raw)

    # Every connector position, longest connector first so "and then" isn't
    # matched as bare "and" leaving a dangling "then".
    marks: list[tuple[int, int]] = []
    low = protected.lower()
    for conn in sorted(_CONNECTORS, key=len, reverse=True):
        # \b doesn't apply to punctuation — ";" and "," need a literal match.
        pat = re.escape(conn) if conn in (";", ",") else r"\b" + re.escape(conn) + r"\b"
        for m in re.finditer(pat, low):
            if any(s <= m.start() < e for s, e in marks):
                continue        # inside a connector we already took
            marks.append((m.start(), m.end()))
    marks.sort()

    clauses, cursor = [], 0
    for start, end in marks:
        after = protected[end:]
        if not _leading_verb(after):
            continue            # "black and decker" — not a boundary
        piece = protected[cursor:start].strip(" ,.;:")
        if piece:
            clauses.append(piece)
        cursor = end
    tail = protected[cursor:].strip(" ,.;:")
    if tail:
        clauses.append(tail)

    clauses = [_restore(_strip_filler(c), store) for c in clauses]
    out: list[str] = []
    for c in clauses:
        out.extend(_split_juxtaposed(c))
    return [c for c in out if c]


# Verbs that can legitimately follow an app name with no connector at all:
# "open browser search bmw m4". Kept deliberately short — a longer list starts
# splitting real app names and filenames ("open read me.txt").
_JUXTAPOSED = ("search for", "search", "google", "look up", "type", "write",
               "ask", "go to", "navigate to", "screenshot", "analyze", "analyse")


def _split_juxtaposed(clause: str) -> list[str]:
    """
    Split "open browser search bmw m4" into two clauses.

    People drop the connector constantly when speaking. Without this the whole
    tail becomes the app name and the launch fails on an app that doesn't exist
    — which reads as Jarvis not understanding a perfectly ordinary sentence.

    Only applied after a launch verb, and only when the words before the second
    verb name an app we actually recognise, so "open read me and weep.txt" is
    left alone.
    """
    hit = _leading_verb(clause)
    if not hit or hit[1] != "open":
        return [clause]
    verb, _, rest = hit
    low = rest.lower()
    best = None
    for v in sorted(_JUXTAPOSED, key=len, reverse=True):
        m = re.search(r"\b" + re.escape(v) + r"\b", low)
        if m and m.start() > 0 and (best is None or m.start() < best[0]):
            best = (m.start(), m.end())
    if not best:
        return [clause]
    head = rest[:best[0]].strip(" ,.;")
    tail = rest[best[0]:].strip(" ,.;")
    if not head or not tail:
        return [clause]
    try:
        if not (_known_app(head) or head.lower() in _BROWSER_WORDS):
            return [clause]
    except Exception:
        return [clause]
    return [f"{verb} {head}", tail]


# ── clause -> intent ─────────────────────────────────────────────────────────

_BROWSER_WORDS = {"browser", "edge", "chrome", "firefox", "web", "internet",
                  "the web", "the internet"}
_PAGE_WORDS = {"page", "the page", "this page", "it", "the results", "results",
               "the screen", "screen", "this", "that"}


def parse_clause(clause: str) -> dict:
    """One clause as {intent, object, raw}. Unknown verbs become intent 'unknown'."""
    hit = _leading_verb(clause)
    if not hit:
        return {"intent": "unknown", "object": clause.strip(), "raw": clause}
    verb, intent, obj = hit
    obj = obj.strip(" .,\"'“”")
    # "ask it how it is" / "tell it hello" — the pronoun is the app we just
    # opened. "me"/"us" points the other way: "tell me a joke" is addressed to
    # Jarvis. Either way the pronoun is not part of the text, and leaving it in
    # is how Notepad ended up containing the characters `me about yourself`.
    obj = re.sub(r"^(?:it|them|him|her|me|us)\s+", "", obj).strip()

    # "tell me about X" is listed as an analyze verb because "tell me about this
    # page" means look at the screen. It only means that when X IS the screen —
    # "tell me about yourself" is a request for writing, and answering it by
    # screenshotting Notepad describes an empty document instead.
    if verb == "tell me about" and obj and obj.lower() not in _PAGE_WORDS:
        intent = "write"
        obj = f"about {obj}"      # keep the subject readable as a writing brief
    return {"intent": intent, "object": obj, "verb": verb, "raw": clause}


# ── intent + context -> steps ────────────────────────────────────────────────

def _wants_composition(intent: str, text: str, verb: str = "", app: str = "") -> bool:
    """
    Defer to tool_registry so both entry points answer this identically.

    The VERB matters, not just the intent: "ask" and "tell" aimed at Notepad
    mean Jarvis should answer and write it down, because there is nothing in
    Notepad to ask. Aimed at Doubao they stay literal — the question is for the
    app. Passing only the intent flattened that distinction.
    """
    try:
        from services.tool_registry import _wants_composition as w
        v = (verb or "").lower()
        if not v.startswith(("ask", "tell")):
            v = "write" if intent == "write" else "type"
        return w(v, text, app)
    except Exception:
        return intent == "write" and len(text.split()) >= 5


def _search_url(query: str) -> str:
    from services.tool_registry import search_url
    return search_url(query)


def _canon_app(word: str) -> str:
    from services.tool_registry import _canon_app as c
    return c(word)


def _known_app(word: str) -> bool:
    from services.tool_registry import _looks_like_known_app as k
    return k(word)


def _steps_for(parsed: dict, ctx: dict) -> list[dict]:
    """
    Turn one parsed clause into executable steps, using and updating `ctx`.

    `ctx` is what makes this a plan rather than a list: it carries the app that
    was opened, the query that was searched and the page that was loaded, so a
    later clause can say "the page" and mean something.
    """
    intent, obj = parsed["intent"], parsed["object"]
    steps: list[dict] = []

    if intent == "open":
        # "open notepad and frobnicate the widget" — only the first word is an
        # app. Truncating at " and " is right, but throwing the rest away
        # silently is not: half the command would run and report success. Keep
        # the remainder so decompose() can say it didn't understand it.
        word, _, tail = obj.partition(" and ")
        word = word.strip() or "browser"
        if tail.strip():
            ctx.setdefault("dropped", []).append(tail.strip())
        if word.lower() in _BROWSER_WORDS or _known_app(word):
            app = _canon_app(word)
            ctx["app"] = app
            ctx["is_browser"] = app in ("edge", "chrome", "firefox", "brave", "opera")
            steps.append({"action": "open_app", "params": {"name_or_path": app}})
            # A browser opened with nothing to load is left alone: a later
            # `search` clause navigates it by URL, which is far more reliable
            # than typing into whatever happens to hold focus.
            if not ctx["is_browser"]:
                steps.append({"action": "wait_for_window",
                              "params": {"title": app, "timeout": 12}})
                ctx["focused"] = True      # a later clause needn't wait again
        else:
            ctx["app"] = None
            steps.append({"action": "open_app", "params": {"name_or_path": word}})
        return steps

    if intent == "close":
        target = obj or ctx.get("app") or ""
        return [{"action": "close_app", "params": {"name_or_path": target}}] if target else []

    if intent == "search":
        query = obj.strip(" ?.")
        if not query:
            return []
        ctx["query"] = query
        browser = ctx.get("app") if ctx.get("is_browser") else ""
        ctx["url"] = _search_url(query)
        ctx["is_browser"] = True
        ctx["app"] = browser or ctx.get("app")
        return [{"action": "open_url",
                 "params": {"url": ctx["url"], "browser": browser, "query": query}}]

    if intent == "navigate":
        url = obj.strip()
        if not url:
            return []
        if not url.startswith("http"):
            url = ("https://" + url) if "." in url.split()[0] else _search_url(url)
        ctx["url"], ctx["is_browser"] = url, True
        return [{"action": "open_url",
                 "params": {"url": url,
                            "browser": ctx.get("app") if ctx.get("is_browser") else ""}}]

    if intent in ("type", "write", "ask"):
        text = obj
        if not text:
            return []
        # A clause with no app of its own inherits the one already open. This is
        # what lets "open notepad, then write about yourself" work at all.
        if ctx.get("app") and not ctx.get("focused"):
            steps.append({"action": "wait_for_window",
                          "params": {"title": ctx["app"], "timeout": 12}})
            ctx["focused"] = True
        composing = _wants_composition(intent, text, parsed.get("verb", ""),
                                       ctx.get("app") or "")
        if composing:
            hint = ""
            try:
                from services import persona
                hint = persona.style_hint()
            except Exception:
                pass
            steps.append({"action": "compose",
                          "params": {"prompt": text, "topic": text, "style": hint}})
        else:
            steps.append({"action": "type_text", "params": {"text": text}})
        # Chat boxes and search fields submit on Enter; editors should not — and
        # composed prose never should, because it IS the answer, not a message
        # being sent to something that will reply to it.
        if not composing and (intent == "ask" or (ctx.get("app") and ctx.get("is_chat_app"))):
            steps.append({"action": "press", "params": {"key": "enter"}})
        return steps

    if intent == "send":
        # Delegated: recipient extraction and the "which messaging app" decision
        # already live in tool_registry and are covered by their own rules.
        from services.tool_registry import resolve_steps
        got = resolve_steps(parsed["raw"])
        return got or []

    if intent == "press":
        key = obj.replace("the ", "").replace(" key", "").strip() or "enter"
        return [{"action": "press", "params": {"key": key}}]

    if intent == "click":
        return [{"action": "click_text", "params": {"text": obj}}] if obj else []

    if intent == "scroll":
        direction = "down" if "down" in obj.lower() or not obj else "up"
        return [{"action": "scroll", "params": {"direction": direction}}]

    if intent == "wait":
        n = re.search(r"(\d+)", obj)
        return [{"action": "wait", "params": {"seconds": int(n.group(1)) if n else 2}}]

    if intent == "screenshot":
        return [{"action": "screenshot", "params": {}}]

    if intent == "analyze":
        # "analyze the page" — say WHAT page. The subject comes from context, so
        # the vision prompt is grounded instead of asking a model to describe
        # "the page" with no idea which one.
        subject = obj.strip(" ?.")
        generic = (not subject) or subject.lower() in _PAGE_WORDS
        if generic and ctx.get("query"):
            question = (f"This is the search results page for '{ctx['query']}'. "
                        f"Summarise what it says about {ctx['query']}. "
                        f"Be specific and use only what is visible.")
        elif generic and ctx.get("app"):
            question = (f"This is {ctx['app']}. Describe what is on screen and "
                        f"what the user could do next.")
        elif generic:
            question = "Describe what is on the screen and suggest a next action."
        else:
            question = f"Looking at the screen, {subject}. Use only what is visible."
        out = []
        if ctx.get("url") and not ctx.get("settled"):
            out.append({"action": "wait", "params": {"seconds": 3}})
            ctx["settled"] = True
        out.append({"action": "screenshot", "params": {}})
        out.append({"action": "analyze", "params": {"question": question,
                                                    "prompt": question}})
        return out

    if intent in ("save", "copy", "paste"):
        key = {"save": "ctrl+s", "copy": "ctrl+c", "paste": "ctrl+v"}[intent]
        return [{"action": "hotkey", "params": {"keys": key}}]

    return []


# ── public entry point ───────────────────────────────────────────────────────

def decompose(text: str) -> dict:
    """
    Full decomposition of a command.

    Returns {ok, clauses, steps, plan, unresolved}:
      clauses     — the sentence broken into steps, for display
      steps       — executable, for desktop_agent.execute_chain
      plan        — one human-readable line per step, for the live planner
      unresolved  — clauses no rule understood; the caller may send these to the
                    LLM. They are reported rather than silently dropped, because
                    quietly discarding half a command is how "it said done and
                    did nothing" happens.
    """
    clauses = split_clauses(text)
    if not clauses:
        return {"ok": False, "clauses": [], "steps": [], "plan": [],
                "unresolved": [], "reason": "nothing to do"}

    # One clause with no connectors is the common case, and tool_registry
    # already has hand-tuned, tested rules for those exact phrasings. Use them.
    if len(clauses) == 1:
        try:
            from services.tool_registry import resolve_steps
            direct = resolve_steps(text)
        except Exception:
            direct = None
        if direct:
            return {"ok": True, "clauses": clauses, "steps": direct,
                    "plan": [describe(s) for s in direct], "unresolved": [],
                    "source": "tool_registry"}

    ctx: dict = {"app": None, "url": None, "query": None,
                 "is_browser": False, "focused": False, "settled": False}
    steps, plan, unresolved = [], [], []

    for clause in clauses:
        parsed = parse_clause(clause)
        if parsed["intent"] == "unknown":
            unresolved.append(clause)
            continue
        got = _steps_for(parsed, ctx)
        if not got:
            unresolved.append(clause)
            continue
        for s in got:
            steps.append(s)
            plan.append(describe(s))

    # Anything a step handler had to discard counts as not understood. Silence
    # here is how "it said done and did half of it" happens.
    unresolved += ctx.get("dropped", [])

    return {"ok": bool(steps), "clauses": clauses, "steps": steps, "plan": plan,
            "unresolved": unresolved, "context": ctx, "source": "decompose"}


def describe(step: dict) -> str:
    """One plain line for a step — what the live planner shows the user."""
    a = (step or {}).get("action", "")
    p = (step or {}).get("params", {}) or {}
    return {
        "open_app":        lambda: f"Open {p.get('name_or_path', '?')}",
        "close_app":       lambda: f"Close {p.get('name_or_path', '?')}",
        "wait_for_window": lambda: f"Wait for {p.get('title', 'the window')} to appear",
        "open_url":        lambda: (f"Search for \"{p['query']}\"" if p.get("query")
                                    else f"Go to {p.get('url', '')[:60]}"),
        "type_text":       lambda: f"Type \"{_clip(p.get('text', ''))}\"",
        "compose":         lambda: f"Write something about \"{_clip(p.get('topic', ''))}\"",
        "press":           lambda: f"Press {p.get('key', 'enter')}",
        "hotkey":          lambda: f"Press {p.get('keys', '')}",
        "click_text":      lambda: f"Click \"{_clip(p.get('text', ''))}\"",
        "scroll":          lambda: f"Scroll {p.get('direction', 'down')}",
        "wait":            lambda: f"Wait {p.get('seconds', 2)}s",
        "screenshot":      lambda: "Take a screenshot",
        "analyze":         lambda: "Look at the screen and answer",
    }.get(a, lambda: a.replace("_", " ").capitalize() or "step")()


def _clip(s: str, n: int = 40) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def preview(text: str) -> dict:
    """Decompose without executing — for 'show me the plan first'."""
    d = decompose(text)
    return {"command": text, "steps": len(d["steps"]), "plan": d["plan"],
            "clauses": d["clauses"], "unresolved": d["unresolved"]}
