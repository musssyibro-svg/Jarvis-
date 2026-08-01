"""
services/persona.py — what Jarvis knows about YOU, permanently.

The complaint behind this module: "it should already know I'm in China, that I
don't have Chrome, that I use QQ, how I like things written." Re-establishing
that in every conversation is what makes an assistant feel generic — it is the
difference between a tool you operate and one that knows you.

Three sources, in increasing authority:

    1. OBSERVED   — read off the machine by environment.py (no Chrome installed,
                    Windows is Chinese, QQ is present). Refreshed on every scan.
    2. INFERRED   — noticed from behaviour (you keep picking Edge, your proposals
                    are short). Written by other services, always with evidence.
    3. STATED     — you said it. Beats both of the above and is never overwritten
                    by a scan.

Facts are injected into planning, composition and proposal prompts as a short
block, so the model has the context without being asked for it. Deliberately
small: a prompt stuffed with a hundred remembered trivia is worse than one with
eight things that matter.

Nothing sensitive lives here. Credentials belong in services/vault.py, which is
encrypted; this file is plain JSON in the settings table and is included in
runtime reports.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from models.db import conn

KEY = "persona_facts"
_lock = threading.Lock()

STATED, INFERRED, OBSERVED = "stated", "inferred", "observed"
_RANK = {OBSERVED: 0, INFERRED: 1, STATED: 2}

# The facts worth knowing, with the question each one answers. Anything not in
# here is rejected, so the store can't silently accumulate junk that then gets
# fed into every prompt.
FIELDS: dict[str, str] = {
    "name":            "what to call you",
    "location":        "where you are (decides search engine, mirrors, language)",
    "languages":       "languages you read and write",
    "browser":         "which browser to use",
    "search_engine":   "which search engine actually loads for you",
    "messaging_app":   "where 'send someone a message' should go",
    "editor":          "where 'write this down' should go",
    "writing_style":   "how you want text composed on your behalf",
    "work_hours":      "when you're at the machine",
    "occupation":      "what you do, for proposals and context",
    "interests":       "recurring subjects, so searches skew usefully",
    "favourite_sites": "sites you go to often",
    "constraints":     "hard limits (no VPN, limited disk, 16GB RAM)",
    "dislikes":        "things never to do without asking",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    try:
        with conn() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (KEY,)).fetchone()
        if row and row["value"]:
            return json.loads(row["value"])
    except Exception:
        pass
    return {}


def _save(facts: dict) -> None:
    with conn() as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                   (KEY, json.dumps(facts, ensure_ascii=False)))


def remember(field: str, value: str, source: str = STATED,
             evidence: str = "") -> dict:
    """
    Record one fact.

    A weaker source never overwrites a stronger one: once you have TOLD Jarvis
    you prefer Firefox, a machine scan finding Edge installed must not quietly
    change it back. That silent reversal is exactly the kind of thing that makes
    a system feel like it isn't listening.
    """
    field = (field or "").strip().lower()
    if field not in FIELDS:
        return {"ok": False, "error": f"'{field}' is not a fact I track",
                "known": sorted(FIELDS)}
    value = (value or "").strip()
    if not value:
        return {"ok": False, "error": "empty value"}

    with _lock:
        facts = _load()
        old = facts.get(field)
        if old and _RANK.get(source, 0) < _RANK.get(old.get("source", OBSERVED), 0):
            return {"ok": False, "skipped": True,
                    "reason": f"you already told me {field} is '{old['value']}'",
                    "kept": old}
        facts[field] = {"value": value, "source": source,
                        "evidence": evidence, "at": _now()}
        _save(facts)

    try:
        from services import event_bus
        event_bus.publish("persona.learned",
                          {"field": field, "value": value, "source": source})
    except Exception:
        pass
    return {"ok": True, "field": field, "value": value, "source": source}


def forget(field: str) -> dict:
    with _lock:
        facts = _load()
        gone = facts.pop((field or "").strip().lower(), None)
        _save(facts)
    return {"ok": bool(gone), "removed": gone}


def all_facts() -> dict:
    return _load()


def get(field: str, default: str = "") -> str:
    f = _load().get((field or "").strip().lower())
    return f["value"] if f else default


# ── seeding from the machine ─────────────────────────────────────────────────

def sync_from_environment() -> dict:
    """
    Read the machine and record what it implies about you.

    Everything written here is `observed`, so any of it can be corrected by
    simply saying so — and the correction sticks.
    """
    try:
        from services import environment
        env = environment.scan()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    learned = []

    browsers = list(env.get("browsers") or {})
    if browsers:
        learned.append(remember("browser", browsers[0], OBSERVED,
                                f"installed browsers: {', '.join(browsers)}"))

    apps = env.get("apps") or {}
    for candidate in ("qq", "wechat", "dingtalk", "telegram", "discord", "slack"):
        if candidate in apps:
            learned.append(remember("messaging_app", candidate, OBSERVED,
                                    f"{candidate} is installed"))
            break
    for candidate in ("notepad++", "vscode", "word", "notepad"):
        if candidate in apps:
            learned.append(remember("editor", candidate, OBSERVED,
                                    f"{candidate} is installed"))
            break

    net = env.get("network") or {}
    loc = env.get("locale") or {}
    if net.get("likely_china"):
        learned.append(remember("location", "mainland China", OBSERVED,
                                "timezone/config indicate mainland China"))
        learned.append(remember("search_engine", "bing-cn", OBSERVED,
                                "Google is unreachable from here without a VPN"))
    if loc.get("language"):
        learned.append(remember("languages", loc["language"], OBSERVED,
                                "system locale"))

    hard = []
    for c in env.get("constraints", []):
        if c.get("key") in ("no_gpu", "limited_ram", "china_network", "low_disk"):
            hard.append(c["fact"])
    if hard:
        learned.append(remember("constraints", "; ".join(hard), OBSERVED,
                                "machine scan"))

    return {"ok": True, "learned": [l for l in learned if l.get("ok")],
            "skipped": [l for l in learned if l.get("skipped")]}


# ── the part that actually changes behaviour ─────────────────────────────────

def prompt_block(max_facts: int = 10) -> str:
    """
    The block injected into planning and composition prompts.

    Ordered by how much each fact changes an answer, and capped — a model given
    forty remembered details starts writing about the details instead of doing
    the task.
    """
    facts = _load()
    if not facts:
        return ""
    priority = ["name", "location", "languages", "occupation", "writing_style",
                "constraints", "browser", "search_engine", "messaging_app",
                "editor", "interests", "dislikes", "work_hours", "favourite_sites"]
    lines = []
    for field in priority:
        f = facts.get(field)
        if f and len(lines) < max_facts:
            lines.append(f"- {FIELDS[field]}: {f['value']}")
    if not lines:
        return ""
    return ("What you already know about this user (don't ask again):\n"
            + "\n".join(lines))


def style_hint() -> str:
    """Composition-specific guidance, empty when the user hasn't expressed one."""
    parts = []
    if s := get("writing_style"):
        parts.append(f"Write in this style: {s}.")
    if l := get("languages"):
        if not l.lower().startswith("en"):
            parts.append(f"The user reads {l}; keep English simple and direct.")
    if d := get("dislikes"):
        parts.append(f"Avoid: {d}.")
    return " ".join(parts)


def status() -> dict:
    """For the UI: every fact, where it came from, and what's still unknown."""
    facts = _load()
    return {
        "known": [{"field": k, **v, "answers": FIELDS.get(k, "")}
                  for k, v in sorted(facts.items())],
        "unknown": [{"field": k, "answers": v}
                    for k, v in sorted(FIELDS.items()) if k not in facts],
        "note": "Say \"remember that I ...\" to set any of these. What you state "
                "beats what I detect, and a machine scan will never overwrite it.",
    }


# ── learning from a sentence ─────────────────────────────────────────────────

_PATTERNS = [
    (r"\bi (?:live|am based|am) in ([a-z一-鿿 ,]+)", "location"),
    (r"\bi(?:'m| am) (?:a|an) ([a-z ]{3,40}?)(?:\.|,|$)", "occupation"),
    (r"\bi (?:use|prefer) ([a-z0-9+.]+) (?:as my )?browser", "browser"),
    (r"\bmy name is ([a-z一-鿿 ]{2,30})", "name"),
    (r"\bcall me ([a-z一-鿿 ]{2,30})", "name"),
    (r"\bi (?:don't|dont|do not|never) (?:want|like) ([a-z ,]{3,60})", "dislikes"),
    (r"\bi work ([a-z0-9 :\-]{3,40})", "work_hours"),
]


def learn_from_text(text: str) -> list[dict]:
    """
    Pick durable facts out of a sentence.

    Only fires on explicit "remember that ..." or clearly self-describing
    statements. Inferring preferences from passing remarks produces a persona
    full of things the user never meant, and those then steer every future
    answer — the cost of a wrong fact here is much higher than a missed one.
    """
    import re
    t = (text or "").strip()
    low = t.lower()
    out = []

    m = re.match(r"^\s*(?:please\s+)?remember(?:\s+that)?\s*[:,]?\s*(.+)$", low)
    explicit = bool(m)
    body = m.group(1).strip() if m else low
    if not explicit and not any(body.startswith(p) for p in
                                ("i am ", "i'm ", "i live ", "my name is ",
                                 "call me ", "i use ", "i prefer ", "i work ")):
        return out

    for pattern, field in _PATTERNS:
        hit = re.search(pattern, body)
        if hit:
            out.append(remember(field, hit.group(1).strip(" .,"), STATED, t[:160]))
    if not out and explicit:
        # An explicit "remember that ..." that matches no field is still worth
        # keeping — dropping it silently is the behaviour being complained about.
        out.append(remember("interests", body[:200], STATED, t[:160]))
    return [o for o in out if o.get("ok")]


def start() -> None:
    """Seed from the machine in the background at startup."""
    threading.Thread(target=lambda: _quiet_sync(), daemon=True).start()


def _quiet_sync():
    try:
        sync_from_environment()
    except Exception:
        pass
