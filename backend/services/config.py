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
    "ask_before_submit":      ("JARVIS_ASK_SUBMIT",      "true"),
}


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
        pass                    # a missing table must not break every lookup
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
    except Exception as e:
        return {"ok": False, "key": key, "error": str(e)[:120]}
    invalidate()
    # Mirror into the environment as well. Anything still reading os.getenv
    # directly (third-party code, a module we haven't migrated) then agrees
    # with the UI instead of silently disagreeing with it.
    env_name = (KNOWN.get(key) or (None, None))[0]
    if env_name and val:
        os.environ[env_name] = val
    return {"ok": True, "key": key, "value": val, "effective": get(key)}


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
        out[key] = {"value": get(key), "source": src,
                    "saved": saved or None, "env": env_val or None,
                    "default": built_in or None}
    return out
