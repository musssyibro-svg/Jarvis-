"""routes/automation.py — Auto Mode + queue management"""
import json, threading
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from models.db import conn

router = APIRouter()

def _now(): return datetime.now(timezone.utc).isoformat()

class AutoRequest(BaseModel):
    platforms: List[str] = ["hubstaff", "remoteok", "weworkremotely"]
    your_name: str = "Ibrahim"
    your_skills: str = "Python, automation, web scraping, AI integration, FastAPI"
    max_jobs: int = 10

@router.post("/start")
async def start_auto(req: AutoRequest, background_tasks: BackgroundTasks):
    """
    V9: Auto Mode now runs through OrchestratorCore (single source of workflow
    state), not services.automation_engine.run_auto_mode (deprecated duplicate
    pipeline). Reads/writes the same automation_queue, so existing queued data
    is preserved, not orphaned.
    """
    from agents.v9_models import Goal
    from agents.orchestrator_core import OrchestratorCore
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
    from agents.orchestrator import STATE
    STATE.set(running=False, stage="stopped")
    STATE.emit("orchestrator", "Auto mode stop requested")
    try:
        from services.income_engine import stop as income_stop
        income_stop()
    except Exception:
        pass
    return {"message": "Stopped orchestrator + income engine"}

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
def list_queue(status: Optional[str] = None, limit: int = 100):
    with conn() as db:
        if status:
            rows = db.execute("SELECT * FROM automation_queue WHERE status=? ORDER BY id DESC LIMIT ?",
                              (status, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM automation_queue ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try: d["payload"] = json.loads(d.get("payload") or "{}")
        except: pass
        result.append(d)
    return {"queue": result, "total": len(result)}


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
    from fastapi.responses import FileResponse
    from pathlib import Path as _P
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
def list_platform_jobs(platform: Optional[str] = None, limit: int = 100):
    with conn() as db:
        if platform:
            rows = db.execute("SELECT * FROM platform_jobs WHERE platform=? ORDER BY id DESC LIMIT ?",
                              (platform, limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM platform_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"jobs": [dict(r) for r in rows], "total": len(rows)}

@router.get("/today-stats")
def today_stats():
    today = _now()[:10]
    with conn() as db:
        jobs_today = db.execute(
            "SELECT COUNT(*) as c FROM platform_jobs WHERE scraped_at LIKE ?", (f"{today}%",)
        ).fetchone()["c"]
        apps_today = db.execute(
            "SELECT COUNT(*) as c FROM automation_queue WHERE created_at LIKE ?", (f"{today}%",)
        ).fetchone()["c"]
        replies_today = db.execute(
            "SELECT COUNT(*) as c FROM proposals WHERE got_reply=1 AND updated_at LIKE ?", (f"{today}%",)
        ).fetchone()["c"]
        hubstaff_jobs = db.execute("SELECT COUNT(*) as c FROM hubstaff_jobs").fetchone()["c"]
        cw_tasks = db.execute("SELECT COUNT(*) as c FROM clickworker_tasks WHERE status='available'").fetchone()["c"]
        zd_tasks = db.execute("SELECT COUNT(*) as c FROM zuodao_tasks WHERE status='available'").fetchone()["c"]
        proposals_sent = db.execute(
            "SELECT COUNT(*) as c FROM proposals WHERE status != 'draft'"
        ).fetchone()["c"]
        won = db.execute("SELECT COUNT(*) as c FROM proposals WHERE won=1").fetchone()["c"]
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
from services.bid_executor import execute_queue_item, execute_all_approved, stop_executor, executor_status

@router.post("/queue/{qid}/execute")
def execute_queue_one(qid: int, background_tasks: BackgroundTasks):
    """Execute a single approved queue item via Playwright."""
    background_tasks.add_task(execute_queue_item, qid)
    return {"message": f"Executing queue item {qid}"}

@router.post("/execute-approved")
def execute_all(background_tasks: BackgroundTasks):
    """Execute ALL approved queue items sequentially."""
    background_tasks.add_task(execute_all_approved)
    return {"message": "Executor started for all approved items"}

@router.post("/executor/stop")
def executor_stop():
    return stop_executor()

@router.get("/executor/status")
def executor_get_status():
    return executor_status()
