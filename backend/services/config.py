"""
services/config.py — one place that answers "what is this setting?"

THE BUG THIS FIXES
------------------
Saving a setting in the UI worked. Nothing read it.

    Settings page  ->  POST /settings/ollama_fast_model  ->  row in SQLite
    ollama_manager ->  os.getenv("OLLAMA_FAST_MODEL")    ->  never sees the row

So you could set the fast model to qwen2.5:3b, save it, refresh, and Diagnostics
would still report "you haven't set this" — because it was reading an
environment variable that was never set, falling back to its default, and the
row you'd written was sitting in the database with nothing looking at it.

There was a second half to it: those values were read at MODULE IMPORT time into
constants. Even after wiring the database in, a change wouldn't take effect
until the backend restarted, which still looks broken from the outside.

HOW IT WORKS NOW
----------------
One lookup order, everywhere:

    1. the settings table   (what you chose in the UI — always wins)
    2. the environment      (.env / system, for people who prefer files)
    3. the built-in default

Read through get() at CALL time, not import time, so a change applies to the
very next request with no restart. Cached for a few seconds so this doesn't add
a database hit to every call, and the cache is dropped the moment anything is
written.
"""
import os
import threading
import time

from models.db import conn

_TTL = 5.0                      # seconds; long enough to matter, short enough to feel live
_lock = threading.Lock()
_cache = {"at": 0.0, "rows": {}}

# key -> (environment variable, default)
#
# The env-var column is what lets an advanced user keep using a .env file, and
# what keeps existing installs working unchanged.
KNOWN = {
    "ollama_fast_model":      ("OLLAMA_FAST_MODEL",      ""),
    "ollama_reasoning_model": ("OLLAMA_REASONING_MODEL", ""),
    "ollama_vision_model":    ("OLLAMA_VISION_MODEL",    ""),
    "ollama_embed_model":     ("OLLAMA_EMBED_MODEL",     "nomic-embed-text"),
    "ollama_url":             ("OLLAMA_URL",             "http://127.0.0.1:11434"),
    "auto_submit":            ("JARVIS_AUTO_SUBMIT",     "false"),
    "income_interval_min":    ("JARVIS_INCOME_INTERVAL", "20"),
    "income_max_jobs":        ("JARVIS_MAX_JOBS",        "15"),
    "income_min_score":       ("JARVIS_MIN_SCORE",       "30"),
    "your_name":              ("JARVIS_USER_NAME",       ""),
    "your_skills":            ("JARVIS_USER_SKILLS",     ""),
    "monitor_inbox":          ("JARVIS_MONITOR_INBOX",   "false"),
    "typing_speed":           ("JARVIS_TYPING_SPEED",    "0.03"),
    # Which search engine actually loads from where the user is. Google does not
    # resolve from mainland China without a VPN, so the default is Bing's China
    # endpoint rather than the one most code would assume.
    "search_engine":          ("JARVIS_SEARCH_ENGINE",   "bing-cn"),
    # Capability overrides. Blank means "use whatever is installed and has been
    # working" — see services/providers.py.
    "provider_web_search":    ("JARVIS_BROWSER",         ""),
    "provider_browse":        ("",                       ""),
    "provider_message":       ("",                       ""),
    "provider_edit_text":     ("",                       ""),
    "provider_terminal":      ("",                       ""),
    # Tuned automatically by services/selfeval.py when a run shows they're wrong.
    "type_settle_s":          ("",                       "0.3"),
    "vision_max_tokens":      ("",                       "320"),
    # Which provider answers which kind of request. Blank means "use the
    # default", and the default is the local Ollama — Jarvis stays entirely
    # offline unless a key is deliberately added. See services/ai_router.py.
    "ai_route_default":       ("JARVIS_AI_PROVIDER",     "ollama"),
    "ai_route_chat":          ("",                       ""),
    "ai_route_reasoning":     ("",                       ""),
    "ai_route_planner":       ("",                       ""),
    "ai_route_coding":        ("",                       ""),
    "ai_route_vision":        ("",                       ""),
    "ai_route_memory":        ("",                       ""),
    "ai_route_proposal":      ("",                       ""),
    "ai_route_browser":       ("",                       ""),
    # Comma-separated providers to try when the first one fails. Ollama is
    # always tried last regardless, so a dead API key degrades to local rather
    # than to an error.
    "ai_fallback":            ("",                       ""),
    # Cloud endpoints. All optional, all off until a key is set. One shape for
    # every vendor — see providers/openai_compatible.py.
    "ai_deepseek_api_key":    ("DEEPSEEK_API_KEY",       ""),
    "ai_deepseek_model":      ("",                       ""),
    "ai_glm_api_key":         ("GLM_API_KEY",            ""),
    "ai_glm_model":           ("",                       ""),
    "ai_kimi_api_key":        ("MOONSHOT_API_KEY",       ""),
    "ai_kimi_model":          ("",                       ""),
    "ai_openrouter_api_key":  ("OPENROUTER_API_KEY",     ""),
    "ai_openrouter_model":    ("",                       ""),
    "ai_openai_api_key":      ("OPENAI_API_KEY",         ""),
    "ai_openai_model":        ("",                       ""),
    "ai_gemini_api_key":      ("GEMINI_API_KEY",         ""),
    "ai_gemini_model":        ("",                       ""),
    "ai_omniroute_base_url":  ("OMNIROUTE_URL",          ""),
    "ai_omniroute_api_key":   ("OMNIROUTE_KEY",          ""),
    "ai_omniroute_model":     ("",                       ""),
    "ai_lmstudio_base_url":   ("",                       ""),
    "ai_lmstudio_model":      ("",                       ""),

    # Security. Defaults are safe for a local single-user run; see services/auth.py.
    "jarvis_require_token":   ("JARVIS_REQUIRE_TOKEN",   "false"),
    "jarvis_check_origin":    ("JARVIS_CHECK_ORIGIN",    "true"),
    "desktop_control_enabled": ("DESKTOP_CONTROL_ENABLED", "true"),
    "ask_before_submit":      ("JARVIS_ASK_SUBMIT",      "true"),
}


def _ensure_table() -> None:
    """
    Create the settings table if it isn't there yet.

    This module used to assume models.db.init_db() had already run. Inside the
    running backend that is true — main.py calls it at startup — but nothing
    else does: tools/, the failure-injection harness and mcp_server.py all
    reach for config on their own.

    On a database where init_db() had never run, set() returned
    {"ok": False, "error": "no such table: settings"} and almost every caller
    ignores that dict. So the value looked saved and wasn't: exactly the
    "I set it, I saved it, nothing changed" failure this module exists to
    prevent, one layer down.

    Found by CI on a fresh checkout. It could not reproduce on any machine
    where Jarvis had been started once — including every dev machine.
    """
    try:
        with conn() as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings ("
                       "key TEXT PRIMARY KEY, value TEXT)")
    except Exception:
        pass        # read-only disk or a locked db — get() still falls back


def _rows() -> dict:
    with _lock:
        if _cache["rows"] and time.time() - _cache["at"] < _TTL:
            return _cache["rows"]
    rows = {}
    try:
        with conn() as db:
            for r in db.execute("SELECT key, value FROM settings").fetchall():
                rows[r["key"]] = r["value"]
    except Exception:
        _ensure_table()         # first read on a fresh database
    with _lock:
        _cache["rows"] = rows
        _cache["at"] = time.time()
    return rows


def invalidate() -> None:
    """Drop the cache so the next read sees a just-saved value."""
    with _lock:
        _cache["rows"], _cache["at"] = {}, 0.0


def get(key: str, default=None) -> str:
    """Setting > environment > declared default > the default passed in."""
    val = (_rows().get(key) or "").strip()
    if val:
        return val
    env_name, built_in = KNOWN.get(key, (None, None))
    if env_name:
        env_val = (os.getenv(env_name) or "").strip()
        if env_val:
            return env_val
    if built_in:
        return built_in
    return default if default is not None else ""


def get_bool(key: str, default: bool = False) -> bool:
    v = get(key, "true" if default else "false").strip().lower()
    return v in ("1", "true", "yes", "on")


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(float(get(key, str(default))))
    except (TypeError, ValueError):
        return default


def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get(key, str(default)))
    except (TypeError, ValueError):
        return default


def set(key: str, value) -> dict:
    """Write a setting and make it live immediately."""
    val = "" if value is None else str(value).strip()
    try:
        with conn() as db:
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                       (key, val))
    except Exception:
        # Most likely the table doesn't exist yet. Create it and try ONCE more,
        # then report honestly if it still fails — a settings write that
        # silently does nothing is worse than one that says it couldn't.
        _ensure_table()
        try:
            with conn() as db:
                db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                           (key, val))
        except Exception as e:
            return {"ok": False, "key": key, "error": str(e)[:120]}
    invalidate()
    # Mirror into the environment as well. Anything still reading os.getenv
    # directly (third-party code, a module we haven't migrated) then agrees
    # with the UI instead of silently disagreeing with it.
    env_name = (KNOWN.get(key) or (None, None))[0]
    if env_name and val:
        os.environ[env_name] = val
    # Capability choices are cached for five minutes, so without this the UI
    # would confirm "browser = firefox" while the next command still opened
    # Edge — the same class of bug this whole module exists to kill.
    if key.startswith("provider_"):
        try:
            from services import providers
            providers.invalidate()
        except Exception:
            pass
    # Same reason: an AI provider is built once and cached, so without this a
    # newly pasted API key wouldn't be used until the next restart.
    if key.startswith("ai_"):
        try:
            from services import ai_router
            ai_router.invalidate()
        except Exception:
            pass
    return {"ok": True, "key": key, "value": val, "effective": get(key)}


# Settings whose VALUE must never be shown. The Settings screen lists every
# effective value, and the runtime report embeds the same thing — which is
# exactly the file the user sends to other people when something breaks. An API
# key travelling in a debug report is a credential leak with a friendly face.
_SECRET_HINTS = ("api_key", "apikey", "_key", "token", "secret", "password", "pwd")


def is_secret(key: str) -> bool:
    k = (key or "").lower()
    return any(h in k for h in _SECRET_HINTS)


def _mask(value: str) -> str:
    """Enough to recognise it, not enough to use it."""
    v = (value or "").strip()
    if not v:
        return ""
    return f"{v[:3]}…{v[-2:]} ({len(v)} chars)" if len(v) > 8 else "•" * len(v)


def effective() -> dict:
    """
    Every known setting with its value AND where that value came from.

    The "where from" is the point. "I set this and it didn't apply" is
    impossible to debug when the UI only shows you what you typed — this shows
    whether the running system agrees with you.
    """
    rows = _rows()
    out = {}
    for key, (env_name, built_in) in KNOWN.items():
        saved = (rows.get(key) or "").strip()
        env_val = (os.getenv(env_name) or "").strip() if env_name else ""
        if saved:
            src = "you set this"
        elif env_val:
            src = f"environment ({env_name})"
        elif built_in:
            src = "built-in default"
        else:
            src = "not set"
        if is_secret(key):
            out[key] = {"value": _mask(get(key)), "source": src, "secret": True,
                        "saved": bool(saved), "env": bool(env_val), "default": None}
        else:
            out[key] = {"value": get(key), "source": src,
                        "saved": saved or None, "env": env_val or None,
                        "default": built_in or None}
    return out
