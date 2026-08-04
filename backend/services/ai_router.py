"""
services/ai_router.py — one door for every AI call in Jarvis.

WHAT IT REPLACES

`call_model` is imported in about thirty files, and `ollama.chat()` is called
directly in two more. Changing model provider therefore meant editing thirty
files and hoping none were missed — and one of the direct calls in main.py
bypassed every cap and fallback the rest of the system had.

Now there is one function:

    ai_router.ask(task="planner", prompt=...)

and the provider is a setting, not a code edit.

TWO ROUTERS, DIFFERENT QUESTIONS — this trips people up

    ai_router      WHICH PROVIDER   local Ollama? DeepSeek? OpenRouter?
    model_router   WHICH MODEL      the strongest one that fits in free RAM

They are not duplicates and neither replaces the other. model_router carries
the machine-specific knowledge that makes Jarvis usable on 16 GB — it is why a
0.5B model correctly wins when memory is at 87%. ai_router sits above it and
never looks at model names at all.

CONFIGURED FROM THE SETTINGS TABLE, NOT A YAML FILE

The proposal that prompted this suggested config/providers.yaml. That would add
a dependency (PyYAML), and — worse — a second source of truth: the Settings
screen already writes to SQLite, so a YAML file means exporting, reloading, and
two places to disagree. Everything here reads services/config.py, which is the
same store the UI edits and which is already read at call time.

    ai_route_<task>     which provider for this task    (blank = ai_route_default)
    ai_route_default    the fallback for everything     (default: ollama)
    ai_fallback         comma-separated chain to try if the first fails

FULLY LOCAL UNLESS YOU SAY OTHERWISE. Nothing cloud is enabled by default; a
provider with no key reports itself unconfigured and is skipped, so Jarvis
behaves exactly as before until the user deliberately adds one.
"""
from __future__ import annotations

import threading
from collections.abc import Generator

_lock = threading.Lock()
_instances: dict[str, object] = {}

# What kind of thinking a caller can ask for. Kept small and intention-shaped:
# these are jobs, not model tiers, so the mapping to an actual model stays a
# provider's business.
TASKS = ("chat", "reasoning", "planner", "coding", "vision",
         "memory", "proposal", "browser")

BUILTIN = "ollama"


def _setting(key: str, default: str = "") -> str:
    try:
        from services import config
        return (config.get(key, default) or "").strip()
    except Exception:
        return default


def _provider(name: str):
    """
    Build (and cache) a provider. Cached because constructing one reads
    settings, and this is on the path of every AI call in the system.
    """
    name = (name or "").strip().lower()
    if not name:
        return None
    with _lock:
        if name in _instances:
            return _instances[name]
    inst = None
    try:
        if name == "ollama":
            from providers.ollama_provider import OllamaProvider
            inst = OllamaProvider()
        else:
            # Everything else is an OpenAI-compatible endpoint. See
            # providers/openai_compatible.py for why that's one file, not six.
            from providers.openai_compatible import OpenAICompatible
            inst = OpenAICompatible(name)
    except Exception:
        inst = None
    with _lock:
        _instances[name] = inst
    return inst


def invalidate() -> None:
    """Drop cached providers so a settings change applies to the next call."""
    with _lock:
        _instances.clear()


def route_for(task: str) -> str:
    """Which provider handles this task."""
    return (_setting(f"ai_route_{task}")
            or _setting("ai_route_default", BUILTIN)
            or BUILTIN)


def chain_for(task: str) -> list[str]:
    """
    Provider order for this task: the chosen one, then the fallbacks.

    Ollama is always appended last. A cloud provider can be rate-limited, out of
    credit, or simply unreachable from behind the GFW, and when that happens the
    right answer is the local model rather than an error — Jarvis is supposed to
    work without the internet.
    """
    out, seen = [], set()
    for name in [route_for(task),
                 *[p.strip() for p in _setting("ai_fallback").split(",")],
                 BUILTIN]:
        n = (name or "").strip().lower()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _messages(prompt: str, history: list | None, system: str | None) -> list[dict]:
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    for h in (history or []):
        role, content = h.get("role"), h.get("content")
        if role in ("user", "assistant", "system") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": prompt})
    return msgs


def _is_error(text: str) -> bool:
    """
    Providers report expected failures as '[...]' rather than raising. That's
    what lets a caller print the result straight to the user — but the router
    has to notice, or a fallback would never fire.
    """
    t = (text or "").strip()
    return t.startswith("[") and t.endswith("]") and len(t) < 400


def ask(task: str = "chat", prompt: str = "", history: list | None = None,
        fast: bool = False, temperature: float = 0.7,
        max_tokens: int | None = None, system_prompt: str | None = None,
        **kwargs) -> str:
    """
    Ask for one answer. Always returns a string, never raises.

    Tries each provider in the chain and moves on when one reports a failure,
    so an expired API key degrades to the local model instead of stopping work.
    """
    if not prompt or not prompt.strip():
        return "[Nothing to ask.]"
    msgs = _messages(prompt, history, system_prompt)
    tried, last = [], ""

    for name in chain_for(task):
        prov = _provider(name)
        if prov is None:
            tried.append(f"{name}: not available")
            continue
        if not prov.configured():
            tried.append(f"{name}: not set up")
            continue
        try:
            out = prov.chat(msgs, temperature=temperature, max_tokens=max_tokens,
                            task=task, **kwargs)
        except Exception as e:                 # a provider that breaks its own contract
            tried.append(f"{name}: {str(e)[:80]}")
            continue
        if out and not _is_error(out):
            _note(task, name, ok=True)
            return out
        last = out or ""
        tried.append(f"{name}: {last[:80]}")

    _note(task, "none", ok=False)
    # Every provider failed. Say what was tried — "[AI error]" with no detail is
    # the kind of message that costs an evening.
    if last:
        return last if len(tried) == 1 else \
            f"{last}\n(Also tried: {'; '.join(tried[:-1])})"
    return f"[No AI provider could answer. Tried: {'; '.join(tried) or 'nothing'}]"


def ask_stream(task: str = "chat", prompt: str = "", history: list | None = None,
               temperature: float = 0.7, max_tokens: int | None = None,
               system_prompt: str | None = None,
               **kwargs) -> Generator[str, None, None]:
    """
    Stream an answer chunk by chunk.

    Falls back only BEFORE the first chunk. Once text has reached the user,
    switching providers mid-answer would splice two different replies together,
    which is worse than an honest truncation.
    """
    if not prompt or not prompt.strip():
        yield "[Nothing to ask.]"
        return
    msgs = _messages(prompt, history, system_prompt)
    tried = []

    for name in chain_for(task):
        prov = _provider(name)
        if prov is None or not prov.configured():
            tried.append(name)
            continue
        started = False
        try:
            for chunk in prov.stream(msgs, temperature=temperature,
                                     max_tokens=max_tokens, task=task, **kwargs):
                if not started and _is_error(chunk):
                    break                      # this provider can't; try the next
                started = True
                yield chunk
        except Exception:
            if started:
                return                         # partial answer already delivered
            tried.append(name)
            continue
        if started:
            _note(task, name, ok=True)
            return
        tried.append(name)

    yield f"[No AI provider could answer. Tried: {', '.join(tried) or 'nothing'}]"


def _note(task: str, provider: str, ok: bool) -> None:
    """Record which provider served a task, so `status()` isn't guesswork."""
    try:
        from services import event_bus
        event_bus.publish("ai.used", {"task": task, "provider": provider, "ok": ok})
    except Exception:
        pass
    with _lock:
        _last_used[task] = {"provider": provider, "ok": ok}


_last_used: dict[str, dict] = {}


def status() -> dict:
    """
    Every provider, whether it's usable, and what would answer each kind of
    request. This is what the Settings screen shows.
    """
    from providers.openai_compatible import PRESETS

    names, seen = [], set()
    for n in [BUILTIN, *PRESETS.keys(),
              *[p.strip().lower() for p in _setting("ai_fallback").split(",")],
              *[route_for(t) for t in TASKS]]:
        if n and n not in seen:
            seen.add(n)
            names.append(n)

    providers = {}
    for n in names:
        prov = _provider(n)
        if prov is None:
            providers[n] = {"ok": False, "reason": "couldn't load", "configured": False}
            continue
        try:
            h = prov.health()
        except Exception as e:
            h = {"ok": False, "reason": str(e)[:120], "models": []}
        h["configured"] = prov.configured()
        h["label"] = getattr(prov, "label", n)
        providers[n] = h

    return {
        "routing": {t: route_for(t) for t in TASKS},
        "fallback": _setting("ai_fallback") or f"(then {BUILTIN})",
        "default": _setting("ai_route_default", BUILTIN),
        "providers": providers,
        "last_used": dict(_last_used),
        "note": ("Jarvis runs entirely on the local Ollama unless you add a key "
                 "for something else. Any provider without one is skipped."),
    }
