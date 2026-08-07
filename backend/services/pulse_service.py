"""
services/pulse_service.py — Jarvis Pulse: the proactive layer.

Everything else in Jarvis waits to be asked. Pulse is the part that speaks
first: a background heartbeat that watches what Jarvis already knows (plans,
scraped jobs, system health) and surfaces anything worth telling the user —
in the Core live feed (SSE) and persisted so the UI can show what happened
while the app was closed.

Design rules:
  - Cheap, local, offline-safe probes only. A pulse tick must never block,
    never call an LLM, and never take more than ~1s.
  - Never nag: every notification has a dedupe key and a cooldown window, so
    the same fact is surfaced at most once per window.
  - Degrade silently: any probe failing is skipped, never crashes the loop.

Public API:
    init_pulse()          -> create table
    start_pulse()         -> start the daemon heartbeat (call once at startup)
    recent(limit, unseen) -> stored notifications, newest first
    mark_seen()           -> flag everything as seen
    tick()                -> run all probes once (used by tests / manual poke)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from models.db import conn

logger = logging.getLogger("jarvis.pulse")

INTERVAL = int(os.getenv("JARVIS_PULSE_INTERVAL", "600"))        # seconds between ticks
COOLDOWN = int(os.getenv("JARVIS_PULSE_COOLDOWN", "21600"))      # 6h per dedupe key

SCHEMA = """
CREATE TABLE IF NOT EXISTS pulse_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT,                -- briefing | plans | jobs | system
    dedupe_key TEXT,
    msg        TEXT NOT NULL,
    level      TEXT DEFAULT 'info',
    seen       INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pulse_dedupe ON pulse_events(dedupe_key, created_at);
"""

_started = False
_start_lock = threading.Lock()


def init_pulse() -> None:
    with conn() as db:
        db.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(kind: str, msg: str, level: str = "info", dedupe_key: str | None = None) -> bool:
    """Store + push a notification. Returns False when suppressed by cooldown."""
    key = dedupe_key or f"{kind}:{msg[:80]}"
    try:
        with conn() as db:
            row = db.execute(
                "SELECT created_at FROM pulse_events WHERE dedupe_key=? "
                "ORDER BY id DESC LIMIT 1", (key,)).fetchone()
            if row:
                try:
                    last = datetime.fromisoformat(row["created_at"])
                    age = (datetime.now(timezone.utc) - last).total_seconds()
                    if age < COOLDOWN:
                        return False
                except Exception:
                    pass
            db.execute(
                "INSERT INTO pulse_events(kind,dedupe_key,msg,level,created_at) "
                "VALUES(?,?,?,?,?)", (kind, key, msg, level, _now()))
    except Exception as e:
        logger.warning(f"pulse store failed: {e}")
    try:
        from agents.orchestrator import STATE
        STATE.emit("pulse", msg, level)
    except Exception:
        pass
    logger.info(f"pulse [{kind}] {msg}")
    return True


# ── Probes ────────────────────────────────────────────────────────────────────

def _probe_plans() -> None:
    """Nudge about projects with work in flight or blocked."""
    with conn() as db:
        rows = db.execute("""
            SELECT p.name,
                   SUM(CASE WHEN s.status='doing'   THEN 1 ELSE 0 END) AS doing,
                   SUM(CASE WHEN s.status='blocked' THEN 1 ELSE 0 END) AS blocked,
                   SUM(CASE WHEN s.status='todo'    THEN 1 ELSE 0 END) AS todo
            FROM plan_projects p JOIN plan_steps s ON s.project_id = p.id
            WHERE p.status='active' GROUP BY p.id""").fetchall()
    for r in rows:
        if r["blocked"]:
            _emit("plans",
                  f"Project '{r['name']}': {r['blocked']} step(s) BLOCKED — "
                  f"want help unblocking? (Plans panel)",
                  "warning", dedupe_key=f"plans:blocked:{r['name']}")
        elif r["doing"]:
            _emit("plans",
                  f"Project '{r['name']}': {r['doing']} step(s) in progress, "
                  f"{r['todo']} to go.",
                  "info", dedupe_key=f"plans:doing:{r['name']}")


def _probe_jobs() -> None:
    """Surface freshly scraped jobs since the last jobs notification."""
    with conn() as db:
        last = db.execute(
            "SELECT created_at FROM pulse_events WHERE kind='jobs' "
            "ORDER BY id DESC LIMIT 1").fetchone()
        since = last["created_at"] if last else "1970"
        rows = db.execute(
            "SELECT title, platform FROM platform_jobs WHERE scraped_at > ? "
            "ORDER BY scraped_at DESC LIMIT 200", (since,)).fetchall()
    if not rows:
        return
    top = rows[0]
    _emit("jobs",
          f"{len(rows)} new job(s) scraped — top: “{(top['title'] or '')[:70]}” "
          f"({top['platform']}). Open Freelance ▸ Jobs.",
          "success", dedupe_key=f"jobs:{len(rows)}:{top['title']}")


def _probe_system() -> None:
    """Warn when the machine itself is about to make Jarvis flaky."""
    try:
        import psutil
        ram_gb = psutil.virtual_memory().available / 1e9
        disk = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
        if ram_gb < 1.5:
            _emit("system", f"Low free RAM ({ram_gb:.1f}GB) — local models may "
                            f"stall. Close some apps.", "warning",
                  dedupe_key="system:ram")
        if disk.free / 1e9 < 3:
            _emit("system", f"Low disk on system drive ({disk.free/1e9:.1f}GB free).",
                  "warning", dedupe_key="system:disk")
    except Exception:
        pass
    try:
        import requests
        url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        requests.get(f"{url}/api/tags", timeout=2)
    except Exception:
        _emit("system", "Ollama isn't running — chat falls back to canned "
                        "replies. Start it with: ollama serve", "warning",
              dedupe_key="system:ollama")


def _probe_queue() -> None:
    """Nudge when generated proposals are sitting unapproved in the queue."""
    try:
        with conn() as db:
            n = db.execute("SELECT COUNT(*) AS n FROM automation_queue "
                           "WHERE status='pending'").fetchone()["n"]
        if n:
            _emit("queue",
                  f"{n} proposal(s) drafted and waiting for your yes/no — "
                  f"Freelance ▸ Auto Mode ▸ Queue.",
                  "warning", dedupe_key=f"queue:pending:{n}")
    except Exception:
        pass


def _probe_replies() -> None:
    """Tell the user the moment a client reply is sitting unread."""
    try:
        with conn() as db:
            n = db.execute("SELECT COUNT(*) AS n FROM messages "
                           "WHERE is_read=0").fetchone()["n"]
        if n:
            _emit("replies",
                  f"📨 {n} unread client message(s) — a proposal may have been "
                  f"answered. Freelance ▸ Messages.",
                  "success", dedupe_key=f"replies:{n}")
    except Exception:
        pass


def briefing() -> str:
    """One-shot situational summary, emitted at startup ('good morning' moment)."""
    parts = []
    try:
        with conn() as db:
            docs = db.execute("SELECT COUNT(*) AS n FROM brain_documents").fetchone()["n"]
            plans = db.execute("""
                SELECT COUNT(*) AS n FROM plan_projects WHERE status='active'""").fetchone()["n"]
            open_steps = db.execute("""
                SELECT COUNT(*) AS n FROM plan_steps s JOIN plan_projects p
                ON p.id=s.project_id
                WHERE p.status='active' AND s.status IN ('todo','doing','blocked')""").fetchone()["n"]
            jobs_today = db.execute(
                "SELECT COUNT(*) AS n FROM platform_jobs WHERE scraped_at >= ?",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d"),)).fetchone()["n"]
        if plans:
            parts.append(f"{plans} active plan(s), {open_steps} open step(s)")
        if docs:
            parts.append(f"{docs} document(s) in the brain")
        if jobs_today:
            parts.append(f"{jobs_today} job(s) scraped today")
    except Exception as e:
        logger.warning(f"briefing probe failed: {e}")
    msg = ("Jarvis online. " + ("; ".join(parts) + "." if parts else
           "Clean slate — feed the Brain, or say 'plan project …' to start one."))
    _emit("briefing", msg, "info", dedupe_key=f"briefing:{datetime.now().strftime('%Y-%m-%d-%H')}")
    return msg


def tick() -> None:
    """Run every probe once; each is independently best-effort."""
    for probe in (_probe_plans, _probe_jobs, _probe_system, _probe_queue, _probe_replies):
        try:
            probe()
        except Exception as e:
            logger.warning(f"pulse probe {probe.__name__} failed: {e}")


def _loop() -> None:
    time.sleep(10)          # let the app finish booting
    try:
        briefing()
    except Exception as e:
        logger.warning(f"briefing failed: {e}")
    while True:
        try:
            tick()
        except Exception as e:
            logger.warning(f"pulse tick failed: {e}")
        time.sleep(INTERVAL)


def start_pulse() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="jarvis-pulse").start()
    logger.info(f"Pulse started (every {INTERVAL}s).")


# ── Read side ────────────────────────────────────────────────────────────────

def recent(limit: int = 20, unseen_only: bool = False) -> list[dict]:
    q = "SELECT * FROM pulse_events"
    if unseen_only:
        q += " WHERE seen=0"
    q += " ORDER BY id DESC LIMIT ?"
    with conn() as db:
        rows = db.execute(q, (limit,)).fetchall()
    return [dict(r) for r in rows]


def mark_seen() -> int:
    with conn() as db:
        cur = db.execute("UPDATE pulse_events SET seen=1 WHERE seen=0")
        return cur.rowcount
