"""routes/automation.py — Auto Mode + queue management"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from models.db import conn

router = APIRouter()

def _now(): return datetime.now(timezone.utc).isoformat()

class AutoRequest(BaseModel):
    platforms: list[str] = ["hubstaff", "remoteok", "weworkremotely"]
    your_name: str = "Ibrahim"
    your_skills: str = "Python, automation, web scraping, AI integration, FastAPI"
    max_jobs: int = 10

@router.post("/start")
async def start_auto(req: AutoRequest, background_tasks: BackgroundTasks = None):
    """
    V9: Auto Mode now runs through OrchestratorCore (single source of workflow
    state), not services.automation_engine.run_auto_mode (deprecated duplicate
    pipeline). Reads/writes the same automation_queue, so existing queued data
    is preserved, not orphaned.
    """
    from agents.orchestrator_core import OrchestratorCore
    from agents.v9_models import Goal
    goal = Goal(
        goal_type="freelance_application",
        objective=f"Auto mode across {', '.join(req.platforms)}",
        constraints={"platforms": req.platforms, "your_name": req.your_name,
                     "your_skills": req.your_skills, "max_jobs": req.max_jobs,
                     "auto_apply": False},   # scheduled/auto runs queue, don't auto-submit
        approval_required=True,
        success_condition={"min_applied": 0},
    )
    core = OrchestratorCore()
    core.set_goal(goal)
    background_tasks.add_task(core.run_full_workflow)
    return {"message": "Auto mode started (OrchestratorCore)", "platforms": req.platforms,
            "goal_id": goal.goal_id}

# ── Freelance profile (persistent — feeds every proposal prompt) ─────────────

@router.get("/profile")
def get_profile():
    from services.profile_service import get_profile as gp
    return gp()

@router.post("/profile")
def save_profile(body: dict):
    from services.profile_service import save_profile as sp
    return sp(body or {})


# ── Income engine (always-on freelance loop) ─────────────────────────────────

@router.get("/income/status")
def income_status():
    from services.income_engine import status
    return status()

@router.post("/income/start")
def income_start(body: dict = None):
    from services.income_engine import start
    b = body or {}
    return start(interval_min=b.get("interval_min"), platforms=b.get("platforms"),
                 max_jobs=b.get("max_jobs"))

@router.post("/income/stop")
def income_stop():
    from services.income_engine import stop
    return stop()

@router.post("/income/run-now")
def income_run_now():
    from services.income_engine import run_once_now
    return run_once_now()


@router.post("/stop")
def stop_auto():
    # Consolidated onto the real orchestrator + income engine. The old code wrote
    # services.automation_engine._state, a dead dict nothing reads — a legacy
    # no-op. Stop both the pipeline feed and the always-on loop.
    # Setting STATE alone was decorative: the running core never read it, so the
    # workflow carried on regardless. Ask the core itself to halt.
    res = {}
    try:
        from agents.orchestrator_core import get_core
        res = get_core().request_stop("auto mode stop")
    except Exception as e:
        res = {"ok": False, "error": str(e)[:120]}
    try:
        from services.income_engine import stop as income_stop
        income_stop()
    except Exception:
        pass
    return {"message": "Stopping - the current step finishes first, then Jarvis halts.",
            **res}

@router.get("/status")
def auto_status():
    # Real state from the orchestrator feed + income engine, not the dead
    # automation_engine._state the old code returned.
    from agents.orchestrator import STATE
    s = STATE.get()
    try:
        from services.income_engine import status as income_status
        s = {**s, "income": income_status()}
    except Exception:
        pass
    return s

@router.get("/queue")
def list_queue(status: str | None = None, limit: int = 100):
    with conn() as db:
        if status:
            rows = db.execute("SELECT * FROM automation_queue WHERE status=? ORDER BY id DESC LIMIT ?",
                              (status, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM automation_queue ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except (ValueError, TypeError):
            # A malformed payload means this row's proposal is unreadable, not
            # that the queue is broken. Leave the raw string in place so it's
            # visible in the UI rather than silently blanked. A bare `except`
            # here also swallowed KeyboardInterrupt and SystemExit.
            pass
        result.append(d)
    return {"queue": result, "total": len(result)}


@router.post("/queue/approve-all")
def approve_all():
    """
    Approve every drafted proposal at once.

    The Earn page showed drafts and no way to act on them, so the pipeline
    stopped dead at "written" with nothing to press. Approving marks them ready
    for the executor; submission still happens through bid_executor, which
    records a receipt for each one.
    """
    with conn() as db:
        cur = db.execute(
            "UPDATE automation_queue SET status='approved', processed_at=? "
            "WHERE status='pending'", (_now(),))
        n = cur.rowcount or 0
    if n:
        try:
            from agents.orchestrator import STATE
            # NOT "submitting now". Approving submits nothing — the executor is
            # a separate, deliberate step. Saying otherwise is why the user
            # pressed Approve all, read that Jarvis was submitting, and then had
            # no idea whether anything had been sent. A false claim of action is
            # worse than no message.
            STATE.emit("executor",
                       f"{n} proposal(s) approved. Nothing has been sent yet - "
                       f"press Submit to send them.", "success")
        except Exception:
            pass
    return {"ok": True, "approved": n, "submitted": 0,
            "message": (f"{n} approved. NOTHING IS SENT YET - press "
                        f"\"Submit {n} approved\" to actually send them."
                        if n else "Nothing was waiting for approval.")}


@router.get("/queue/outcome")
def queue_outcome():
    """
    One honest answer to "did it send, and what happened?".

    The submit endpoint starts a background thread and returns "Executor
    started", which tells you nothing about the result. The user's words:
    "I press approve all but I don't know what's going on, if it sent it".
    This reports the real state of every item plus the last few receipts, so
    the page can say "3 sent, 1 needs login" instead of going quiet.
    """
    from services.bid_executor import executor_status
    counts, recent = {}, []
    with conn() as db:
        for row in db.execute("SELECT status, COUNT(*) c FROM automation_queue "
                              "GROUP BY status").fetchall():
            counts[row["status"]] = row["c"]
        rows = db.execute("SELECT id, job_title, platform, status, payload "
                          "FROM automation_queue WHERE status IN "
                          "('done','failed','ready','needs_login') "
                          "ORDER BY processed_at DESC LIMIT 8").fetchall()
    for r in rows:
        try:
            rec = (json.loads(r["payload"] or "{}") or {}).get("receipt") or {}
        except Exception:
            rec = {}
        recent.append({
            "id": r["id"], "job_title": r["job_title"], "platform": r["platform"],
            "status": r["status"],
            "confirmed_by_site": rec.get("confirmed_by_site"),
            "has_proof": bool(rec.get("proof_screenshot")),
            "message": rec.get("message", ""),
        })

    ex = executor_status()
    sent = counts.get("done", 0)
    unconfirmed = sum(1 for x in recent
                      if x["status"] == "done" and x["confirmed_by_site"] is False)
    if ex.get("running"):
        headline = (f"Submitting now - {ex.get('approved', 0)} left to send.")
    elif not counts:
        headline = "Nothing in the queue yet."
    else:
        bits = []
        if sent:
            bits.append(f"{sent} sent"
                        + (f" ({unconfirmed} the site didn't confirm - check Proof)"
                           if unconfirmed else ""))
        if counts.get("ready"):
            bits.append(f"{counts['ready']} ready to apply by hand (job boards "
                        f"have no bid form)")
        if counts.get("needs_login"):
            bits.append(f"{counts['needs_login']} blocked - not logged in")
        if counts.get("failed"):
            bits.append(f"{counts['failed']} failed")
        if counts.get("approved"):
            bits.append(f"{counts['approved']} approved but NOT sent - press Submit")
        if counts.get("pending"):
            bits.append(f"{counts['pending']} drafted, awaiting your approval")
        headline = " · ".join(bits) or "Nothing has happened yet."
    return {"running": bool(ex.get("running")), "counts": counts,
            "headline": headline, "recent": recent}


@router.post("/queue/{qid}/approve")
def approve_one(qid: int):
    with conn() as db:
        db.execute("UPDATE automation_queue SET status='approved', processed_at=? "
                   "WHERE id=? AND status IN ('pending','ready')", (_now(), qid))
    return {"ok": True, "id": qid, "status": "approved"}


@router.post("/queue/{qid}/reject")
def reject_one(qid: int):
    with conn() as db:
        db.execute("UPDATE automation_queue SET status='rejected', processed_at=? "
                   "WHERE id=?", (_now(), qid))
    return {"ok": True, "id": qid, "status": "rejected"}


@router.get("/queue/{qid}/receipt")
def queue_receipt(qid: int):
    """
    What Jarvis ACTUALLY did for this item: the exact proposal text it sent,
    the URL it ended on, whether the site confirmed it, and a screenshot of the
    page after submitting.

    This exists because "it says it submitted" is not evidence. Without a
    receipt there is no way to tell a real submission from a silent failure,
    and no reason to trust the engine with anything unattended.
    """
    with conn() as db:
        row = db.execute("SELECT * FROM automation_queue WHERE id=?", (qid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such queue item")
    d = dict(row)
    try:
        payload = json.loads(d.get("payload") or "{}")
    except Exception:
        payload = {}
    receipt = payload.get("receipt")
    job = payload.get("job", {}) or {}
    return {
        "id": qid,
        "status": d.get("status"),
        "platform": d.get("platform"),
        "job_title": d.get("job_title"),
        "job_url": job.get("link") or (receipt or {}).get("job_url"),
        # The proposal is shown whether or not it was sent — you should be able
        # to read what Jarvis wrote BEFORE approving it, not only afterwards.
        "proposal_text": payload.get("application") or (receipt or {}).get("submitted_text"),
        "receipt": receipt,
        "proof_url": (f"/automation/proof/{receipt['proof_screenshot']}"
                      if receipt and receipt.get("proof_screenshot") else None),
        "note": (None if receipt else
                 "Not submitted yet - no receipt. Approve it, or turn on "
                 "auto-submit, and a receipt is recorded the moment it is sent."),
    }


@router.get("/proof/{path:path}")
def get_proof(path: str):
    """Serve a submission screenshot. Confined to the screenshots folder."""
    from pathlib import Path as _P

    from fastapi.responses import FileResponse
    root = (_P(__file__).resolve().parent.parent / "screenshots").resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "no such proof")
    return FileResponse(str(target), media_type="image/png")

@router.patch("/queue/{qid}/status")
def update_queue_item(qid: int, status: str):
    with conn() as db:
        db.execute("UPDATE automation_queue SET status=?,processed_at=? WHERE id=?",
                   (status, _now(), qid))
        row = db.execute("SELECT * FROM automation_queue WHERE id=?", (qid,)).fetchone()
    return dict(row)

@router.delete("/queue/{qid}")
def delete_queue_item(qid: int):
    with conn() as db:
        db.execute("DELETE FROM automation_queue WHERE id=?", (qid,))
    return {"success": True}

@router.delete("/queue")
def clear_queue():
    with conn() as db:
        db.execute("DELETE FROM automation_queue WHERE status='done'")
    return {"success": True}

@router.get("/platform-jobs")
def list_platform_jobs(platform: str | None = None, limit: int = 100):
    with conn() as db:
        if platform:
            rows = db.execute("SELECT * FROM platform_jobs WHERE platform=? ORDER BY id DESC LIMIT ?",
                              (platform, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM platform_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"jobs": [dict(r) for r in rows], "total": len(rows)}

@router.get("/today-stats")
def today_stats():
    """
    Dashboard counters.

    Every count is isolated. This used to be one `with conn()` block of bare
    queries, so a single missing table — hubstaff_jobs on a fresh install, say —
    500'd the WHOLE endpoint and the dashboard showed nothing at all. A count
    that can't be taken is 0, not a reason to hide the other seven.
    """
    today = _now()[:10]

    def count(sql, args=()):
        try:
            with conn() as db:
                row = db.execute(sql, args).fetchone()
            return (row["c"] if row else 0) or 0
        except Exception:
            return 0

    jobs_today = count("SELECT COUNT(*) as c FROM platform_jobs WHERE scraped_at LIKE ?", (f"{today}%",))
    apps_today = count("SELECT COUNT(*) as c FROM automation_queue WHERE created_at LIKE ?", (f"{today}%",))
    replies_today = count("SELECT COUNT(*) as c FROM proposals WHERE got_reply=1 AND updated_at LIKE ?", (f"{today}%",))
    hubstaff_jobs = count("SELECT COUNT(*) as c FROM hubstaff_jobs")
    cw_tasks = count("SELECT COUNT(*) as c FROM clickworker_tasks WHERE status='available'")
    zd_tasks = count("SELECT COUNT(*) as c FROM zuodao_tasks WHERE status='available'")
    proposals_sent = count("SELECT COUNT(*) as c FROM proposals WHERE status != 'draft'")
    won = count("SELECT COUNT(*) as c FROM proposals WHERE won=1")
    return {
        "jobs_today":       jobs_today,
        "apps_generated":   apps_today,
        "replies_today":    replies_today,
        "hubstaff_total":   hubstaff_jobs,
        "cw_tasks_avail":   cw_tasks,
        "zd_tasks_avail":   zd_tasks,
        "proposals_sent":   proposals_sent,
        "projects_won":     won,
        "active_platforms": _active_platforms(),
    }

def _active_platforms():
    platforms = []
    with conn() as db:
        if db.execute("SELECT COUNT(*) as c FROM hubstaff_jobs").fetchone()["c"] > 0:
            platforms.append("Hubstaff")
        if db.execute("SELECT COUNT(*) as c FROM platform_jobs WHERE platform='remoteok'").fetchone()["c"] > 0:
            platforms.append("RemoteOK")
        if db.execute("SELECT COUNT(*) as c FROM clickworker_tasks").fetchone()["c"] > 0:
            platforms.append("Clickworker")
        if db.execute("SELECT COUNT(*) as c FROM zuodao_tasks").fetchone()["c"] > 0:
            platforms.append("Zuodao")
        if db.execute("SELECT COUNT(*) as c FROM fiverr_gigs").fetchone()["c"] > 0:
            platforms.append("Fiverr")
    return platforms

# ── Bid Executor (runs only on approved items) ───────────────────────────────
# NOTE: single canonical executor route set. The frontend uses these paths.
from services.bid_executor import (
    execute_all_approved,
    execute_queue_item,
    executor_status,
    stop_executor,
)


@router.post("/queue/{qid}/execute")
def execute_queue_one(qid: int, background_tasks: BackgroundTasks):
    """Execute a single approved queue item via Playwright."""
    background_tasks.add_task(execute_queue_item, qid)
    return {"message": f"Executing queue item {qid}"}

@router.post("/execute-approved")
def execute_all(background_tasks: BackgroundTasks):
    """
    Execute ALL approved queue items sequentially.

    Says how many and where to watch. "Executor started" told the user nothing
    about what was happening or when it would be over, which is most of the
    reason they couldn't tell whether anything had been sent.
    """
    with conn() as db:
        n = db.execute("SELECT COUNT(*) c FROM automation_queue "
                       "WHERE status='approved'").fetchone()["c"]
    if not n:
        return {"message": "Nothing is approved, so nothing was sent.",
                "submitting": 0}
    background_tasks.add_task(execute_all_approved)
    return {"submitting": n,
            "message": f"Sending {n} proposal(s) now. Each one saves a receipt - "
                       f"press Proof on a row to see exactly what was sent."}

@router.post("/executor/stop")
def executor_stop():
    return stop_executor()

@router.get("/executor/status")
def executor_get_status():
    return executor_status()
