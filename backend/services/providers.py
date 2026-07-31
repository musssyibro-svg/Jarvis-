"""
services/providers.py — "what do I use for THIS, on THIS machine?"

Jarvis used to think in apps: "browser" meant Chrome, full stop. On a PC without
Chrome that's a guaranteed failure, and the user has to name Edge every single
time — the machine is expected to match the code.

This inverts it. Jarvis thinks in CAPABILITIES ("search the web", "message
someone", "edit text") and resolves each one to the best provider that is
actually present, right now, on this computer. The code adapts to the machine.

Resolution order, most authoritative first:

    1. what you explicitly chose     (settings: provider_web_search = "firefox")
    2. what is actually installed    (in the order listed below)
    3. what has WORKED here          (experience.py success rates re-rank ties)

Point 3 is the part that matters over time. If QQ fails half its launches on
this machine and WeChat never does, "message someone" should stop picking QQ —
without anyone editing a list. That is learned from real observations, not
assumed.

Deliberately NOT model-driven. This runs on the hot path of every command and
has to be instant and predictable; asking an LLM "which browser should I use"
would be slower, non-deterministic, and no more correct than looking at the disk.
"""
import os
import shutil
import threading
import time

_CACHE_TTL = 300.0
_lock = threading.Lock()
_cache: dict = {}


# capability -> ordered candidate providers (best first, all else equal)
#
# Order encodes a real preference, not alphabet. Edge leads on Windows because
# it ships with the OS — it is the one browser guaranteed to exist — and shares
# Chrome's engine, so anything automated against one works against the other.
CAPABILITIES: dict[str, dict] = {
    "web_search": {
        "label": "search the web",
        "providers": ["edge", "chrome", "firefox"],
        "fallback": "edge",
    },
    "browse": {
        "label": "open a web page",
        "providers": ["edge", "chrome", "firefox"],
        "fallback": "edge",
    },
    "message": {
        "label": "send someone a message",
        # China-first, because that is where this machine is. A machine with
        # only Telegram installed still resolves correctly — presence decides.
        "providers": ["qq", "wechat", "dingtalk", "telegram", "discord", "slack"],
        "fallback": None,      # no sane default: refuse rather than guess wrong
    },
    "edit_text": {
        "label": "write or edit text",
        "providers": ["notepad", "notepad++", "vscode", "word"],
        "fallback": "notepad",
    },
    "terminal": {
        "label": "run a command",
        "providers": ["powershell", "cmd"],
        "fallback": "cmd",
    },
    "files": {
        "label": "browse files",
        "providers": ["explorer"],
        "fallback": "explorer",
    },
}

# Known Windows install locations. Checked before the slower resolver paths.
_KNOWN_PATHS = {
    "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "firefox": [r"C:\Program Files\Mozilla Firefox\firefox.exe"],
    "notepad": [r"C:\Windows\System32\notepad.exe"],
    "explorer": [r"C:\Windows\explorer.exe"],
    "cmd": [r"C:\Windows\System32\cmd.exe"],
    "powershell": [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"],
}


def _installed(name: str) -> bool:
    """Is this provider actually on this machine?"""
    for p in _KNOWN_PATHS.get(name, []):
        if os.path.exists(p):
            return True
    if shutil.which(name):
        return True
    # Anything the app resolver has already found (Start Menu, registry) counts.
    # This is how QQ, WeChat and Doubao get detected without a hardcoded path.
    try:
        from services.app_resolver import resolve as _resolve
        return bool(_resolve(name))
    except Exception:
        return False


def _reliability(name: str) -> float | None:
    """How often has launching this actually worked here? None if untried."""
    try:
        from services import experience
        r = experience.reliability(name, "open_app")
        if r.get("samples", 0) >= 4 and r.get("rate") is not None:
            return float(r["rate"])
    except Exception:
        pass
    return None


def resolve(capability: str, refresh: bool = False) -> dict:
    """
    Pick the provider for a capability. Never raises.

    Returns {provider, why, alternatives, installed, preferred} — the `why` is
    for the UI, so "which browser will it use?" has a visible answer instead of
    being a surprise at execution time.
    """
    spec = CAPABILITIES.get(capability)
    if not spec:
        return {"capability": capability, "provider": None,
                "why": f"'{capability}' is not a known capability",
                "alternatives": [], "installed": []}

    with _lock:
        hit = _cache.get(capability)
        if hit and not refresh and time.time() - hit["at"] < _CACHE_TTL:
            return hit["result"]

    # 1. explicit choice always wins, even over "not detected" — the user may
    #    know about an install we can't see.
    preferred = ""
    try:
        from services import config
        preferred = (config.get(f"provider_{capability}", "") or "").strip().lower()
    except Exception:
        pass

    present = [p for p in spec["providers"] if _installed(p)]

    if preferred:
        result = {"capability": capability, "provider": preferred,
                  "why": "you chose this in Settings",
                  "alternatives": [p for p in present if p != preferred],
                  "installed": present, "preferred": preferred}
    elif not present:
        fb = spec.get("fallback")
        result = {"capability": capability, "provider": fb,
                  "why": (f"nothing for '{spec['label']}' was found on this PC"
                          + (f"; trying {fb} anyway" if fb else
                             " — install one of: " + ", ".join(spec["providers"]))),
                  "alternatives": [], "installed": [], "preferred": None}
    else:
        # 2 + 3: keep the listed order, but demote anything that has actually
        # been failing here. A provider with no history keeps its place — an
        # unknown is not evidence of a problem.
        def rank(p):
            rel = _reliability(p)
            demote = 1 if (rel is not None and rel < 0.6) else 0
            return (demote, spec["providers"].index(p))

        ordered = sorted(present, key=rank)
        best = ordered[0]
        rel = _reliability(best)
        why = "installed on this PC"
        if len(present) > 1:
            why += f" (also available: {', '.join(p for p in ordered[1:])})"
        demoted = [p for p in present if (_reliability(p) or 1) < 0.6]
        if demoted:
            why += f"; avoiding {', '.join(demoted)} — unreliable here"
        if rel is not None:
            why += f"; {int(rel * 100)}% success so far"
        result = {"capability": capability, "provider": best, "why": why,
                  "alternatives": ordered[1:], "installed": present,
                  "preferred": None}

    with _lock:
        _cache[capability] = {"at": time.time(), "result": result}
    return result


def provider_for(capability: str) -> str | None:
    """Just the name."""
    return resolve(capability).get("provider")


def invalidate() -> None:
    with _lock:
        _cache.clear()


def status() -> dict:
    """
    Every capability and what Jarvis would use for it — for the UI and the
    runtime report. Answers "why did it open Edge?" before you have to ask.
    """
    invalidate()
    return {"capabilities": {c: resolve(c) for c in CAPABILITIES},
            "note": "Set provider_<capability> in Settings to override any of these."}
