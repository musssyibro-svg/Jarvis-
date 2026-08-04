"""
test_executor.py — Verify bid executor (final).
- SKIP when Playwright not installed
- Safety gate: PENDING refused
- Approved path: Playwright actually launches, navigates, attempts form fill
- Evidence: STATE.emit log captured, queue status change, navigator log
- RAM monitoring throughout
"""
import json
import os
import sys
import tempfile
import time
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from _harness import (
    ARTIFACTS,
    TestRun,
    dump_ollama_status,
    dump_process_list,
    guard,
    ram_snapshot,
    register_temp,
    save_ram_artifact,
)

FAKE_JOB_URL = "https://www.freelancer.com/projects/python/test-verification-99999999"


def run() -> dict:
    t   = TestRun("test_executor")
    ram = []
    ram.append(t.ram("start"))

    # ── Temp DB ───────────────────────────────────────────────────────────────
    tmpdb = tempfile.mktemp(suffix=".db")
    register_temp(tmpdb)
    os.environ["JARVIS_DB"] = tmpdb

    db = guard(t, "import models.db",
               lambda: __import__("models.db", fromlist=["conn","init_db","init_v5"]))
    if db is None:
        return t.finish()

    db.DB_PATH = Path(tmpdb)
    guard(t, "init_db",  lambda: db.init_db())
    c = db.conn()
    guard(t, "init_v5",  lambda: db.init_v5(c))
    c.commit(); c.close()

    bx = guard(t, "import bid_executor",
               lambda: __import__("services.bid_executor",
                                  fromlist=["execute_queue_item","execute_all_approved",
                                            "executor_status","stop_executor"]))
    if bx is None:
        return t.finish()

    # ── Helper: insert queue item ─────────────────────────────────────────────
    def insert(status):
        payload = json.dumps({
            "job": {"link": FAKE_JOB_URL, "title": "Test Project",
                    "budget": "$50", "description": "Automate data entry"},
            "application": "I can complete this project efficiently.",
        })
        cc = db.conn()
        cc.execute(
            "INSERT INTO automation_queue "
            "(platform,job_id,job_title,action,payload,status,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("freelancer", f"job_{status}", f"Test ({status})",
             "submit_bid", payload, status, "2026-01-01T00:00:00Z"))
        cc.commit()
        qid = cc.execute(
            "SELECT id FROM automation_queue ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
        cc.close()
        return qid

    def get_queue_status(qid):
        cc = db.conn()
        row = cc.execute(
            "SELECT status FROM automation_queue WHERE id=?", (qid,)
        ).fetchone()
        cc.close()
        return dict(row) if row else {}

    # ── Safety gate: PENDING must be refused ──────────────────────────────────
    pending_qid = guard(t, "insert PENDING item", lambda: insert("pending"))
    if pending_qid is not None:
        res = guard(t, "execute on PENDING",
                    lambda: bx.execute_queue_item(pending_qid))
        refused = (res is not None
                   and res.get("success") is False
                   and "approved" in (res.get("message", "")).lower())
        t.check("executor refuses PENDING items (safety gate)",
                refused,
                evidence={"qid": pending_qid, "response": res},
                error=None if refused else "executor did not refuse pending item")

    # ── Playwright availability check ─────────────────────────────────────────
    try:
        from playwright.sync_api import sync_playwright
        has_pw = True
    except ImportError:
        has_pw = False

    if not has_pw:
        t.skip("playwright not installed — executor browser test requires: "
               "pip install playwright && playwright install msedge")
        ram.append(t.ram("end_no_playwright"))
        t.add_artifact(save_ram_artifact(ram, "executor"))
        return t.finish()

    # ── Approved item path ────────────────────────────────────────────────────
    t.add_artifact(dump_process_list("before_executor"))
    ram.append(t.ram("before_executor"))

    approved_qid = guard(t, "insert APPROVED item", lambda: insert("approved"))
    if approved_qid is None:
        return t.finish()

    # Capture the STATE feed emitted by the executor to prove navigation ran
    feed_events = []
    try:
        from agents.orchestrator import STATE
        original_emit = STATE.emit

        def capture_emit(agent, msg, level="info"):
            feed_events.append({"agent": agent, "msg": msg, "level": level})
            original_emit(agent, msg, level)

        STATE.emit = capture_emit
        patched = True
    except Exception:
        patched = False
        t.log("Could not patch STATE.emit — feed capture skipped")

    # Also capture stdout (executor prints progress)
    stdout_buf = StringIO()

    def run_executor():
        with redirect_stdout(stdout_buf):
            return bx.execute_queue_item(approved_qid, headless=True)

    ram.append(t.ram("before_playwright_launch"))
    res = guard(t, "execute_queue_item on APPROVED item", run_executor)
    ram.append(t.ram("after_playwright_launch"))

    if patched:
        try:
            STATE.emit = original_emit
        except Exception:
            pass

    stdout_out = stdout_buf.getvalue()
    feed_log   = json.dumps(feed_events, indent=2) if feed_events else "(no feed events)"

    # Save navigator log
    nav_log_path = str(ARTIFACTS / f"executor_nav_{int(time.time())}.txt")
    Path(nav_log_path).write_text(
        f"=== stdout ===\n{stdout_out}\n\n"
        f"=== STATE feed events ===\n{feed_log}",
        encoding="utf-8"
    )
    t.add_artifact(nav_log_path)
    t.log(f"Feed events captured: {len(feed_events)}")
    for ev in feed_events[:10]:
        t.log(f"  [{ev.get('level')}] {ev.get('agent')}: {ev.get('msg')}")

    # executor ran without crashing
    t.check("executor ran approved-item code path without crashing",
            res is not None,
            evidence={"result": res,
                      "feed_event_count": len(feed_events),
                      "stdout_len": len(stdout_out)})

    # Playwright attempted navigation (feed must contain "Opening job page" or similar)
    nav_attempted = any(
        any(kw in ev.get("msg", "").lower()
            for kw in ("opening", "navigating", "goto", "job page", "playwright",
                       "executing", "bid", "form", "fill", "submit"))
        for ev in feed_events
    )
    t.check("Playwright navigation attempted (feed confirms)",
            nav_attempted,
            evidence={"navigation_keywords_found": nav_attempted,
                      "feed_events": feed_events[:8],
                      "feed_event_count": len(feed_events)},
            error=None if nav_attempted
                  else "no navigation evidence in feed — executor may not have reached Playwright")

    # Queue item status must have changed from 'approved'
    qst = guard(t, "read queue status after run", lambda: get_queue_status(approved_qid))
    changed = (qst or {}).get("status", "approved") != "approved"
    t.check("queue item status changed from 'approved'",
            changed,
            evidence={"status_after": (qst or {}).get("status"),
                      "expected_not": "approved"},
            error=None if changed else "status still 'approved' — executor may not have run")

    # executor_status
    st = guard(t, "executor_status()", lambda: bx.executor_status())
    t.check("executor_status returns status dict with 'running' key",
            isinstance(st, dict) and "running" in st,
            evidence={"status": st})

    t.add_artifact(dump_process_list("after_executor"))
    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "executor"))

    return t.finish()


if __name__ == "__main__":
    run()
