"""
services/experience.py — why a step failed, and what Jarvis has learned about it.

Until now every failure was the same failure. `execute_chain` reported "type_text
could not be verified: typed but the text isn't in the focused field", and the
only recovery available was "try the identical thing again". That's why the same
problems kept recurring: nothing distinguished "Chrome needed six seconds to draw
its window" from "there is no vision model installed" from "Cloudflare is showing
a challenge page", and all three got the same blind retry.

This module does two things:

1. CLASSIFY. Turn a raw error string into a `kind` with a plain-English cause, a
   concrete remedy, and — crucially — whether retrying could possibly help. A
   missing model is not a transient error; retrying it three times just wastes
   nine seconds and then reports the same thing.

2. LEARN. Record how each target actually behaves on THIS machine and feed that
   back into execution. If QQ has taken 7.4 seconds to show a window on the last
   five launches, stop waiting 8 seconds by default and hoping — wait what QQ
   actually needs. If a target fails on first launch and succeeds on the retry,
   remember that and pre-emptively allow the retry.

Everything learned is observed, never assumed: with no history the advice is
exactly the old default, so a fresh install behaves the way it always did and
gets better from there.

Deliberately NOT here: any attempt to have an LLM diagnose failures. Diagnosis
that runs on every failed step must be instant and must work when the model is
the thing that's broken.
"""
import re
import statistics
import threading
from datetime import datetime, timezone

from models.db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS experience_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    target     TEXT,        -- app name, platform, or '' for general
    action     TEXT,        -- open_app / type_text / submit_bid ...
    ok         INTEGER,     -- 1 success, 0 failure
    kind       TEXT,        -- failure kind (empty on success)
    duration_s REAL,
    detail     TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_exp_target ON experience_events(target, action);
CREATE INDEX IF NOT EXISTS idx_exp_created ON experience_events(created_at);
"""

_init_lock = threading.Lock()
_ready = False

# How many recent observations to consider per target/action.
WINDOW = 40
# Action name for the pure "how long until this app's window existed" measurement.
# Kept separate from 'open_app' (which times a whole chain step and would skew
# the estimate upward with focus/settle time that isn't the app's fault).
WINDOW_READY = "window_ready"
# Never wait less/more than this for a window, whatever history says.
MIN_WAIT_S, MAX_WAIT_S = 2.0, 25.0
DEFAULT_WAIT_S = 8.0


# ── Failure taxonomy ─────────────────────────────────────────────────────────
#
# kind -> (human cause, remedy, retryable, recovery hint for the executor)
#
# `retryable` is about THIS failure, immediately. "Install a model" is not
# retryable even though it's fixable — retrying cannot change the outcome.
KINDS = {
    # Note the remedy wording: typing is in desktop_agent._NO_RETRY, so Jarvis
    # deliberately does NOT retype — a blind retry would duplicate text in a
    # field that may have received it after all. Promising a retry here would be
    # a lie. Retryable stays True because non-typing actions (clicks in a chain,
    # subsequent steps) genuinely benefit from a re-focus first.
    "focus_lost": (
        "The window wasn't accepting keyboard input, so the text didn't land where it should.",
        "Click the window you want Jarvis to type into, then ask again. Jarvis "
        "won't retype on its own — that risks entering the text twice.",
        True, "refocus"),
    "app_not_found": (
        "Windows couldn't find that application.",
        "Open it manually once so Jarvis can learn its real path, or give the full .exe path.",
        False, "resolve_path"),
    "app_slow": (
        "The app was still starting when Jarvis moved on.",
        "Jarvis now waits longer for this app specifically.",
        True, "wait_longer"),
    "window_never_appeared": (
        "The app was launched but no window ever appeared.",
        "It may have opened minimised, on another desktop, or failed to start.",
        True, "wait_longer"),
    "no_model": (
        "No local model is installed for this kind of work.",
        "Run: ollama pull qwen2.5:3b   (and llava:7b for screen understanding)",
        False, "needs_setup"),
    "model_too_small": (
        "The installed model is too small to follow this instruction reliably.",
        "Run: ollama pull qwen2.5:3b — under ~1B parameters can't hold multi-step instructions.",
        False, "needs_setup"),
    "model_timeout": (
        "The model took too long to answer.",
        "Usually memory pressure. Close some apps, or use a smaller model.",
        True, "reduce_load"),
    "ocr_missing": (
        "Tesseract OCR isn't installed, so text can't be read off the screen.",
        "Install Tesseract and make sure it's on PATH.",
        False, "needs_setup"),
    "ocr_timeout": (
        "Reading text off the screen took too long and was cut off.",
        "Jarvis will analyse a smaller region next time.",
        True, "reduce_scope"),
    "login_required": (
        "You're not logged in to that site.",
        "Open the login once from the Earn screen — the session is then reused.",
        False, "needs_login"),
    "bot_challenge": (
        "The site showed a bot check (Cloudflare / captcha).",
        "Jarvis will back off from this site and retry later; solving it needs you.",
        False, "backoff"),
    "network": (
        "The site or service couldn't be reached.",
        "Check the connection. If you're behind the GFW, this site may need a proxy.",
        True, "backoff"),
    "browser_busy": (
        "Another job was using the browser.",
        "Jarvis will queue this and run it when the browser is free.",
        True, "queue"),
    "element_not_found": (
        "The thing Jarvis was looking for wasn't on screen.",
        "The site's layout may have changed, or the page hadn't finished loading.",
        True, "wait_longer"),
    "permission": (
        "Windows refused the action.",
        "This usually needs Jarvis to run as administrator.",
        False, "needs_setup"),
    "clipboard_unavailable": (
        "Jarvis couldn't verify the typing because the clipboard was in use.",
        "Harmless — the text may well have been typed; Jarvis just can't prove it.",
        True, "retry"),
    "emergency_stop": (
        "Emergency stop is engaged.",
        "Clear it from the Computer screen before Jarvis can control the desktop.",
        False, "needs_setup"),
    # A refusal, not a failure. Retrying is pointless and would only repeat the
    # refusal; the cause is filled in from the check that said no, because a
    # blocked URL has ONE specific reason and a generic "it failed" would send
    # the user hunting for a bug that isn't there.
    "blocked": (
        "Jarvis refused to open that address.",
        "If you meant it, open it in your browser yourself.",
        False, "none"),
    "unknown": (
        "Jarvis couldn't determine why this failed.",
        "The full error is in the runtime report on the Diagnostics screen.",
        True, "retry"),
}

# Ordered: first match wins, so specific patterns precede general ones.
_PATTERNS = [
    ("emergency_stop",   r"emergency stop"),
    ("clipboard_unavailable", r"clipboard (unavailable|in use)|couldn't verify"),
    ("focus_lost",       r"isn't in the focused field|didn't have keyboard focus|foreground|could not focus|not accepting input"),
    ("app_not_found",    r"cannot find|not found|no such file|is not recognized|could not resolve .* path|not installed or not on path"),
    ("window_never_appeared", r"did not appear within|no window with|window .* not found"),
    ("app_slow",         r"still (starting|loading)|not ready yet"),
    ("model_too_small",  r"too small|below the quality"),
    ("no_model",         r"no models installed|no suitable model|ollama pull|not pulled|model .* missing"),
    ("model_timeout",    r"(model|ollama|llm).*(timed? ?out|timeout)|timeout.*(model|ollama)"),
    ("ocr_missing",      r"tesseract.*(not installed|not found)|tesseractnotfound"),
    ("ocr_timeout",      r"ocr.*(timed? ?out|timeout)|timeout.*ocr"),
    ("login_required",   r"not logged in|login required|needs[_ ]login|session expired|sign in"),
    ("bot_challenge",    r"cloudflare|captcha|are you a robot|challenge|access denied|403"),
    ("browser_busy",     r"browser busy|owned by"),
    ("network",          r"connection (refused|reset|aborted)|timed out|unreachable|dns|net::|max retries|ssl|proxy"),
    ("element_not_found", r"not on screen|no match|element not found|selector|could not find .* on screen"),
    ("permission",       r"permission denied|access is denied|accessdenied|not permitted|administrator"),
]


def classify(error: str, action: str = "", result: dict | None = None) -> dict:
    """
    Turn an error message into a structured, actionable failure.
    Always returns something usable — never raises, never returns None.
    """
    text = " ".join(str(x) for x in [
        error or "",
        (result or {}).get("error", ""),
        (result or {}).get("verify_reason", ""),
        (result or {}).get("message", ""),
    ]).lower()

    # A deliberate refusal carries its own explanation and must not be pattern-
    # matched into something else — "is on your local network" contains the word
    # "network", which would classify a security decision as a connection fault
    # and then retry it.
    if (result or {}).get("blocked"):
        cause, remedy, retryable, recovery = KINDS["blocked"]
        raw = (result or {}).get("error") or error or ""
        return {"kind": "blocked", "cause": raw[:300] or cause, "remedy": remedy,
                "retryable": retryable, "recovery": recovery, "raw": raw[:300]}

    kind = "unknown"
    for name, pattern in _PATTERNS:
        if re.search(pattern, text):
            kind = name
            break

    # The ACTION overrules a pattern that can't apply to it.
    #
    # From the 2026-08-05 report: launching "new notepad" failed with "no
    # matching window opened", the substring "no match" hit element_not_found,
    # and the user was told "the site's layout may have changed, or the page
    # hadn't finished loading" — a BROWSER remedy for a desktop app launch.
    # A confidently wrong fix is worse than "unknown": it sends someone to look
    # at the wrong thing entirely.
    if action == "open_app" and kind in ("element_not_found", "unknown"):
        kind = "app_not_found"

    # Action context sharpens a few otherwise-ambiguous cases.
    if kind == "unknown":
        if action in ("type_text", "press", "hotkey"):
            kind = "focus_lost"
        elif action == "open_app":
            kind = "app_not_found"
        elif action in ("analyze_screen", "ocr", "read_screen"):
            kind = "ocr_timeout"

    cause, remedy, retryable, recovery = KINDS[kind]

    # If nothing matched but the action TOLD us what went wrong, say that
    # instead of "Jarvis couldn't determine why this failed." The generic line
    # is for when we genuinely don't know; printing it over a perfectly good
    # explanation — "never saw an edge process" — is a lie by omission, and it
    # sends the user to the diagnostics screen to read what we already had.
    said = (error or (result or {}).get("verify_reason")
            or (result or {}).get("error") or "").strip()
    if kind == "unknown" and len(said) > 12:
        cause = said[:300]

    return {"kind": kind, "cause": cause, "remedy": remedy,
            "retryable": retryable, "recovery": recovery,
            "raw": (error or "")[:300]}


# ── Learning ─────────────────────────────────────────────────────────────────

def _ensure():
    global _ready
    if _ready:
        return
    with _init_lock:
        if _ready:
            return
        try:
            with conn() as db:
                db.executescript(SCHEMA)
            _ready = True
        except Exception:
            pass          # a broken db must never stop the desktop working


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(target: str, action: str, ok: bool, duration_s: float | None = None,
           kind: str = "", detail: str = "") -> None:
    """Log one observation. Best-effort: never raises into the caller."""
    _ensure()
    try:
        with conn() as db:
            db.execute(
                "INSERT INTO experience_events "
                "(target,action,ok,kind,duration_s,detail,created_at) VALUES (?,?,?,?,?,?,?)",
                ((target or "").strip().lower()[:80], action or "", 1 if ok else 0,
                 kind or "", float(duration_s) if duration_s is not None else None,
                 (detail or "")[:300], _now()))
    except Exception:
        pass


def _recent(target: str, action: str, limit: int = WINDOW) -> list[dict]:
    _ensure()
    try:
        with conn() as db:
            rows = db.execute(
                "SELECT ok, kind, duration_s FROM experience_events "
                "WHERE target=? AND action=? ORDER BY id DESC LIMIT ?",
                ((target or "").strip().lower()[:80], action, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def launch_wait_for(app: str) -> dict:
    """
    How long to wait for THIS app's window, learned from what it actually did.

    Uses a high percentile of observed successful launch times rather than the
    mean: an app that usually takes 2s but sometimes takes 9s must be waited on
    for 9s, or one launch in five silently types into the wrong window. With no
    history this returns exactly the old default, so nothing regresses.
    """
    rows = [r for r in _recent(app, WINDOW_READY) if r["ok"] and r["duration_s"]]
    times = sorted(r["duration_s"] for r in rows)
    if len(times) < 3:
        return {"wait_s": DEFAULT_WAIT_S, "learned": False,
                "samples": len(times), "why": "not enough observations yet"}

    # p90 + a second of headroom, clamped to something sane.
    idx = min(len(times) - 1, int(round(0.9 * (len(times) - 1))))
    wait = max(MIN_WAIT_S, min(MAX_WAIT_S, times[idx] + 1.0))
    return {"wait_s": round(wait, 1), "learned": True, "samples": len(times),
            "median_s": round(statistics.median(times), 1),
            "slowest_s": round(times[-1], 1),
            "why": f"{app} has taken up to {times[-1]:.1f}s to show a window here"}


def needs_extra_attempt(target: str, action: str) -> dict:
    """
    Does this target habitually fail its first attempt and succeed on a retry?
    (QQ and some Electron apps do exactly this on a cold start.)
    """
    rows = _recent(target, action, limit=20)
    if len(rows) < 5:
        return {"extra": False, "why": "not enough observations yet"}
    fails = sum(1 for r in rows if not r["ok"])
    rate = fails / len(rows)
    if rate >= 0.3:
        return {"extra": True, "fail_rate": round(rate, 2), "samples": len(rows),
                "why": f"{target} has failed {fails} of its last {len(rows)} "
                       f"{action} attempts here — allowing an extra try"}
    return {"extra": False, "fail_rate": round(rate, 2), "samples": len(rows)}


def reliability(target: str = "", action: str = "") -> dict:
    """Observed success rate. `target`/`action` empty means 'everything'."""
    _ensure()
    where, args = [], []
    if target:
        where.append("target=?"); args.append(target.strip().lower()[:80])
    if action:
        where.append("action=?"); args.append(action)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        with conn() as db:
            rows = db.execute(
                f"SELECT ok, kind FROM experience_events {clause} "
                f"ORDER BY id DESC LIMIT ?", (*args, WINDOW)).fetchall()
    except Exception:
        rows = []
    if not rows:
        return {"samples": 0, "rate": None, "top_failure": None}
    ok = sum(1 for r in rows if r["ok"])
    kinds: dict[str, int] = {}
    for r in rows:
        if not r["ok"] and r["kind"]:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    top = max(kinds.items(), key=lambda kv: kv[1])[0] if kinds else None
    return {"samples": len(rows), "rate": round(ok / len(rows), 2),
            "top_failure": top,
            "top_failure_cause": KINDS.get(top, ("",))[0] if top else None}


def confidence(steps: list) -> dict:
    """
    How likely is this plan to actually work, before we run it?

    Built from what has genuinely been observed — per-action success rates and
    per-app history — plus hard blockers (no model installed, emergency stop).
    A plan with no history scores 0.7: honest uncertainty, not false optimism.

    The point is not the number. The point is that Jarvis can say "I'll try, but
    QQ has failed 4 of its last 6 launches" BEFORE spending two minutes on it.
    """
    steps = steps or []
    if not steps:
        return {"score": 0.0, "label": "nothing to do", "factors": [], "blockers": []}

    factors, blockers = [], []
    score = 0.7

    for s in steps:
        action = (s or {}).get("action", "")
        params = (s or {}).get("params", {}) or {}
        target = params.get("name_or_path") or params.get("app") or ""

        r = reliability(target, action) if target else reliability("", action)
        if r["samples"] >= 3 and r["rate"] is not None:
            # Blend towards the observed rate — more samples, more weight.
            weight = min(0.6, r["samples"] / 40)
            score = score * (1 - weight) + r["rate"] * weight
            what = f"{target} {action}" if target else action
            factors.append(f"{what}: {int(r['rate']*100)}% success over "
                           f"{r['samples']} runs" +
                           (f" (usually {r['top_failure']})" if r["top_failure"] else ""))

    # Hard blockers — things that make the plan impossible, not merely unlikely.
    try:
        from agents.desktop_agent import is_estopped
        if is_estopped():
            blockers.append(KINDS["emergency_stop"][0])
    except Exception:
        pass
    needs_model = any((s or {}).get("action") in
                      ("analyze_screen", "ask_model", "plan", "summarize") for s in steps)
    if needs_model:
        try:
            from services import model_router
            if not model_router.pick_model("chat"):
                blockers.append(KINDS["no_model"][0])
        except Exception:
            pass

    if blockers:
        score = 0.0
    score = max(0.0, min(1.0, score))
    label = ("blocked" if blockers else
             "very likely" if score >= 0.85 else
             "likely" if score >= 0.65 else
             "uncertain" if score >= 0.4 else "unlikely")
    return {"score": round(score, 2), "label": label,
            "factors": factors[:6], "blockers": blockers}


def summary(limit: int = 8) -> dict:
    """What Jarvis has learned, for the Diagnostics screen."""
    _ensure()
    out = {"overall": reliability(), "apps": [], "recent_failures": []}
    try:
        with conn() as db:
            apps = db.execute(
                "SELECT target, COUNT(*) n, SUM(ok) ok FROM experience_events "
                "WHERE target != '' GROUP BY target ORDER BY n DESC LIMIT ?",
                (limit,)).fetchall()
            for a in apps:
                learned = launch_wait_for(a["target"])
                out["apps"].append({
                    "app": a["target"], "runs": a["n"],
                    "success_rate": round((a["ok"] or 0) / a["n"], 2),
                    "learned_wait_s": learned["wait_s"] if learned["learned"] else None,
                    "note": learned["why"] if learned["learned"] else None})
            fails = db.execute(
                "SELECT target, action, kind, detail, created_at FROM experience_events "
                "WHERE ok=0 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            for f in fails:
                k = KINDS.get(f["kind"] or "unknown", KINDS["unknown"])
                out["recent_failures"].append({
                    "app": f["target"], "action": f["action"], "kind": f["kind"],
                    "cause": k[0], "remedy": k[1], "at": f["created_at"]})
    except Exception as e:
        out["error"] = str(e)[:120]
    return out
