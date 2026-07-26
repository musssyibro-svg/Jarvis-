"""
services/platform_health.py — per-site reliability: history, backoff, auto-pause.

An autonomous system that scrapes the same dead site every 20 minutes forever is
just noise. This tracks how each platform actually performs and lets the income
engine skip the ones that are wasting its time:

  * record(platform, ok, jobs, error) after every scan
  * failing sites get exponential backoff (skip 1, then 2, 4, 8 cycles…)
  * a site that fails 6 times in a row is auto-paused and reported once
  * should_scan(platform) is the single gate the engine asks

Kept as data + a gate, so it integrates INTO the existing income engine rather
than becoming a second scanning system.
"""
from datetime import datetime, timezone

from models.db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_health (
    platform        TEXT PRIMARY KEY,
    ok_count        INTEGER DEFAULT 0,
    fail_count      INTEGER DEFAULT 0,
    consecutive_fails INTEGER DEFAULT 0,
    jobs_total      INTEGER DEFAULT 0,
    last_ok         TEXT,
    last_error      TEXT,
    skip_cycles     INTEGER DEFAULT 0,   -- how many upcoming cycles to skip
    paused          INTEGER DEFAULT 0,
    updated_at      TEXT
);
"""

MAX_FAILS_BEFORE_PAUSE = 6
MAX_BACKOFF = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_health() -> None:
    with conn() as db:
        db.executescript(SCHEMA)


def _row(platform: str) -> dict:
    init_health()
    with conn() as db:
        r = db.execute("SELECT * FROM platform_health WHERE platform=?", (platform,)).fetchone()
    return dict(r) if r else {"platform": platform, "ok_count": 0, "fail_count": 0,
                              "consecutive_fails": 0, "jobs_total": 0, "last_ok": None,
                              "last_error": None, "skip_cycles": 0, "paused": 0}


def record(platform: str, ok: bool, jobs: int = 0, error: str = "") -> dict:
    """Log the outcome of one scan and update backoff/pause state."""
    h = _row(platform)
    if ok:
        h["ok_count"] += 1
        h["consecutive_fails"] = 0
        h["skip_cycles"] = 0
        h["paused"] = 0
        h["jobs_total"] += int(jobs or 0)
        h["last_ok"] = _now()
        h["last_error"] = None
    else:
        h["fail_count"] += 1
        h["consecutive_fails"] += 1
        h["last_error"] = (error or "")[:200]
        # exponential backoff: 1, 2, 4, 8 cycles
        h["skip_cycles"] = min(MAX_BACKOFF, 2 ** max(0, h["consecutive_fails"] - 1))
        if h["consecutive_fails"] >= MAX_FAILS_BEFORE_PAUSE:
            h["paused"] = 1
            _announce_pause(platform, h["last_error"])
    _save(h)
    return h


def _save(h: dict) -> None:
    init_health()
    with conn() as db:
        db.execute(
            "INSERT INTO platform_health(platform,ok_count,fail_count,consecutive_fails,"
            "jobs_total,last_ok,last_error,skip_cycles,paused,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(platform) DO UPDATE SET ok_count=excluded.ok_count,"
            " fail_count=excluded.fail_count, consecutive_fails=excluded.consecutive_fails,"
            " jobs_total=excluded.jobs_total, last_ok=excluded.last_ok,"
            " last_error=excluded.last_error, skip_cycles=excluded.skip_cycles,"
            " paused=excluded.paused, updated_at=excluded.updated_at",
            (h["platform"], h["ok_count"], h["fail_count"], h["consecutive_fails"],
             h["jobs_total"], h["last_ok"], h["last_error"], h["skip_cycles"],
             h["paused"], _now()))


def should_scan(platform: str) -> tuple[bool, str]:
    """The gate the income engine asks before scanning a platform."""
    h = _row(platform)
    if h.get("paused"):
        return False, f"paused after {h['consecutive_fails']} straight failures"
    if h.get("skip_cycles", 0) > 0:
        h["skip_cycles"] -= 1          # burn one skip per cycle
        _save(h)
        return False, f"backing off ({h['skip_cycles'] + 1} cycle(s) left)"
    return True, "ok"


def resume(platform: str) -> dict:
    """Un-pause a platform the user has fixed (e.g. logged back in)."""
    h = _row(platform)
    h.update(paused=0, skip_cycles=0, consecutive_fails=0)
    _save(h)
    return {"ok": True, "platform": platform}


def all_health() -> list[dict]:
    init_health()
    with conn() as db:
        rows = db.execute("SELECT * FROM platform_health ORDER BY platform").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        total = d["ok_count"] + d["fail_count"]
        d["success_rate"] = round(100 * d["ok_count"] / total) if total else None
        out.append(d)
    return out


def summary() -> dict:
    h = all_health()
    return {"platforms": h,
            "paused": [x["platform"] for x in h if x["paused"]],
            "best": max(h, key=lambda x: x["jobs_total"])["platform"] if h else None}


def _announce_pause(platform: str, error: str) -> None:
    try:
        from services import event_bus
        event_bus.publish("freelance.platform_paused",
                          {"platform": platform, "error": (error or "")[:120]},
                          emit_feed=True, level="warning")
    except Exception:
        pass
    try:
        from services import pulse_service
        pulse_service._emit("jobs",
                            f"Paused {platform} — it failed {MAX_FAILS_BEFORE_PAUSE} times "
                            f"in a row. Fix it (or log in) and resume from Earn.",
                            "warning", dedupe_key=f"platform:paused:{platform}")
    except Exception:
        pass
