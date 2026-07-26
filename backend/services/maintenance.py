"""
services/maintenance.py — keeps a 24/7 Jarvis from eating a 16GB machine alive.

Left alone, three things grow without bound and eventually kill the box:
the automation queue, chat/event history, and the screenshots folder (one PNG per
screen analysis adds up fast).

Cadence matters as much as the cleanup. One audit suggested VACUUM after every
queue cleanup — that would freeze SQLite for seconds at a time, repeatedly, on
the exact machine we're trying to protect. So:

    every hour   WAL checkpoint  (cheap, keeps the -wal file from ballooning)
    every day    prune old rows + old screenshots
    every week   VACUUM          (expensive, so exactly once, when idle)

Everything is best-effort and never interrupts real work: if the browser or a
workflow is busy, maintenance defers to the next tick.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models.db import conn

logger = logging.getLogger("jarvis.maintenance")

BASE_DIR = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = BASE_DIR / "screenshots"

KEEP_QUEUE_DAYS      = 14      # done/failed/rejected queue rows
KEEP_CHAT_MESSAGES   = 2000    # per session cap
KEEP_SCREENSHOT_DAYS = 3
KEEP_PULSE_DAYS      = 30
KEEP_EXPERIENCE_DAYS = 90      # learned behaviour is worth keeping a long time
KEEP_EXPERIENCE_ROWS = 5000    # …but not forever
MAX_SCREENSHOT_MB    = 500

_started = False
_last = {"checkpoint": 0.0, "daily": 0.0, "weekly": 0.0}
_stats = {"runs": 0, "rows_pruned": 0, "files_deleted": 0, "mb_freed": 0.0,
          "last_run": None, "last_error": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _busy() -> bool:
    """Don't do housekeeping while real work is in flight."""
    try:
        from core.browser_lock import current_owner
        if current_owner().get("name"):
            return True
    except Exception:
        pass
    try:
        from agents.orchestrator import STATE
        if STATE.get().get("running"):
            return True
    except Exception:
        pass
    return False


# ── Individual jobs ───────────────────────────────────────────────────────────

def wal_checkpoint() -> dict:
    """Fold the write-ahead log back into the db. Cheap; safe to run hourly."""
    try:
        with conn() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def prune_rows() -> dict:
    """Delete rows that are old and finished. Never touches pending work."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_QUEUE_DAYS)).isoformat()
    pulse_cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_PULSE_DAYS)).isoformat()
    exp_cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_EXPERIENCE_DAYS)).isoformat()
    removed = 0
    try:
        with conn() as db:
            # finished queue items only — pending/approved are live work
            cur = db.execute(
                "DELETE FROM automation_queue WHERE status IN "
                "('done','failed','rejected','ready') AND created_at < ?", (cutoff,))
            removed += cur.rowcount or 0
            try:
                cur = db.execute("DELETE FROM pulse_events WHERE created_at < ?",
                                 (pulse_cutoff,))
                removed += cur.rowcount or 0
            except Exception:
                pass
            # Learned-behaviour observations. Keep these longer than events —
            # they're what makes Jarvis better at THIS machine — but cap them so
            # a year of running doesn't leave a table nothing ever reads past
            # the newest 40 rows per app.
            try:
                cur = db.execute(
                    "DELETE FROM experience_events WHERE created_at < ? AND id NOT IN "
                    "(SELECT id FROM experience_events ORDER BY id DESC LIMIT ?)",
                    (exp_cutoff, KEEP_EXPERIENCE_ROWS))
                removed += cur.rowcount or 0
            except Exception:
                pass
            # cap chat history per session (keep the newest N)
            try:
                sessions = [r["session_id"] for r in db.execute(
                    "SELECT DISTINCT session_id FROM chat_messages").fetchall()]
                for s in sessions:
                    cur = db.execute(
                        "DELETE FROM chat_messages WHERE session_id=? AND id NOT IN "
                        "(SELECT id FROM chat_messages WHERE session_id=? "
                        " ORDER BY id DESC LIMIT ?)", (s, s, KEEP_CHAT_MESSAGES))
                    removed += cur.rowcount or 0
            except Exception:
                pass
        _stats["rows_pruned"] += removed
        return {"ok": True, "rows": removed}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def prune_screenshots() -> dict:
    """Delete old screenshots, and trim by size if the folder is still large."""
    if not SCREENSHOT_DIR.exists():
        return {"ok": True, "deleted": 0}
    deleted, freed = 0, 0.0
    cutoff = time.time() - KEEP_SCREENSHOT_DAYS * 86400
    try:
        files = []
        for f in SCREENSHOT_DIR.glob("*.png"):
            try:
                st = f.stat()
                files.append((f, st.st_mtime, st.st_size))
            except OSError:
                continue
        # 1) age-based
        for f, mtime, size in files:
            if mtime < cutoff:
                try:
                    f.unlink(); deleted += 1; freed += size
                except OSError:
                    pass
        # 2) size-based: if still over budget, drop oldest first
        remaining = [(f, m, s) for f, m, s in files if f.exists()]
        total_mb = sum(s for _, _, s in remaining) / 1e6
        if total_mb > MAX_SCREENSHOT_MB:
            remaining.sort(key=lambda x: x[1])          # oldest first
            for f, _, size in remaining:
                if total_mb <= MAX_SCREENSHOT_MB:
                    break
                try:
                    f.unlink(); deleted += 1; freed += size; total_mb -= size / 1e6
                except OSError:
                    pass
        _stats["files_deleted"] += deleted
        _stats["mb_freed"] += freed / 1e6
        return {"ok": True, "deleted": deleted, "mb_freed": round(freed / 1e6, 1)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def vacuum() -> dict:
    """Reclaim disk. EXPENSIVE — weekly only, and never while busy."""
    try:
        with conn() as db:
            db.execute("VACUUM")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def unload_idle_models() -> dict:
    """Free a heavy model from RAM when nothing is running (16GB machines)."""
    try:
        from services import model_router
        vision = model_router.pick("vision").get("model")
        if vision:
            return model_router.unload(vision)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    return {"ok": True, "note": "nothing to unload"}


# ── Scheduler ─────────────────────────────────────────────────────────────────

def run_due(force: bool = False) -> dict:
    """Run whatever is due. Called by the loop; safe to call manually."""
    now = time.time()
    did = {}
    if _busy() and not force:
        return {"skipped": "busy"}

    if force or now - _last["checkpoint"] > 3600:            # hourly
        did["wal_checkpoint"] = wal_checkpoint()
        _last["checkpoint"] = now

    if force or now - _last["daily"] > 86400:                # daily
        did["prune_rows"] = prune_rows()
        did["prune_screenshots"] = prune_screenshots()
        did["unload_models"] = unload_idle_models()
        _last["daily"] = now

    if force or now - _last["weekly"] > 7 * 86400:           # weekly
        did["vacuum"] = vacuum()
        _last["weekly"] = now

    if did:
        _stats["runs"] += 1
        _stats["last_run"] = _now()
        logger.info(f"maintenance: {', '.join(did.keys())}")
        try:
            from services import event_bus
            event_bus.publish("system.maintenance", {"jobs": list(did.keys())})
        except Exception:
            pass
    return did or {"skipped": "nothing due"}


def stats() -> dict:
    size_mb = None
    try:
        db_path = BASE_DIR / "jarvis.db"
        if db_path.exists():
            size_mb = round(db_path.stat().st_size / 1e6, 1)
    except Exception:
        pass
    shots = 0
    try:
        shots = len(list(SCREENSHOT_DIR.glob("*.png"))) if SCREENSHOT_DIR.exists() else 0
    except Exception:
        pass
    return {**_stats, "db_mb": size_mb, "screenshots": shots,
            "next": {"checkpoint_in_s": max(0, int(3600 - (time.time() - _last["checkpoint"]))),
                     "daily_in_s": max(0, int(86400 - (time.time() - _last["daily"])))}}


def _loop():
    time.sleep(120)                 # let startup settle
    # Stagger the first daily/weekly so a fresh install doesn't VACUUM at boot.
    _last["daily"] = time.time() - 80000
    _last["weekly"] = time.time()
    while True:
        try:
            run_due()
        except Exception as e:
            _stats["last_error"] = str(e)[:200]
            logger.warning(f"maintenance tick failed: {e}")
        time.sleep(600)             # check every 10 minutes


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="jarvis-maintenance").start()
    logger.info("Maintenance started (hourly checkpoint · daily prune · weekly vacuum).")
