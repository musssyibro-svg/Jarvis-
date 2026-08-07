"""
routes/proposals.py
Full proposal lifecycle: generate → send → track → work → submit
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.db import conn
from services.deepseek_service import auto_work_job
from services.deepseek_service import generate_proposal as ai_generate

router = APIRouter()

VALID_STATUSES = {
    "draft", "sent", "verifying", "accepted", "working", "done",
    "submitted", "rejected", "manual_required", "not_awarded_yet", "not_logged_in",
}


# ── Models ────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    job_id: str
    job_title: str
    job_description: str
    budget: str = "Not specified"
    platform: str = "freelancer"
    skills: list[str] = []
    job_link: str = ""
    your_name: str = "Ibrahim"
    your_skills: str = "Python, automation, web scraping, AI integration, FastAPI"
    tone: str = "professional"


class StatusUpdate(BaseModel):
    status: str
    got_reply: bool | None = None
    won: bool | None = None


class WorkUpdate(BaseModel):
    work_output: str
    work_status: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/generate")
def generate_proposal_route(req: GenerateRequest):
    """Generate AI proposal + confidence + workability analysis."""
    result = ai_generate(
        job_title=req.job_title,
        job_desc=req.job_description,
        budget=req.budget,
        skills=req.skills,
        platform=req.platform,
        your_name=req.your_name,
        your_skills=req.your_skills,
        tone=req.tone,
    )
    now = _now()
    with conn() as db:
        cur = db.execute(
            """INSERT INTO proposals
               (job_id, platform, job_title, job_desc, budget, job_link, skills,
                proposal_text, confidence, can_auto_work, work_type, work_reason,
                status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                req.job_id, req.platform, req.job_title, req.job_description,
                req.budget, req.job_link, json.dumps(req.skills),
                result.get("proposal_text", ""),
                result.get("confidence", 0),
                1 if result.get("can_auto_work") else 0,
                result.get("work_type", "other"),
                result.get("work_reason", ""),
                "draft", now, now,
            ),
        )
        pid = cur.lastrowid

    return {
        "id": pid,
        "job_id": req.job_id,
        "job_title": req.job_title,
        "proposal_text": result.get("proposal_text", ""),
        "confidence": result.get("confidence", 0),
        "can_auto_work": result.get("can_auto_work", False),
        "work_type": result.get("work_type"),
        "work_reason": result.get("work_reason"),
        "status": "draft",
    }


@router.get("/")
def list_proposals(status: str | None = None, limit: int = 100):
    with conn() as db:
        if status:
            rows = db.execute(
                "SELECT * FROM proposals WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM proposals ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return {"proposals": [dict(r) for r in rows]}


@router.get("/{pid}")
def get_proposal(pid: int):
    with conn() as db:
        row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@router.patch("/{pid}/status")
def update_status(pid: int, body: StatusUpdate):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Valid: {VALID_STATUSES}")
    now = _now()
    with conn() as db:
        updates = ["status=?", "updated_at=?"]
        values: list = [body.status, now]
        if body.got_reply is not None:
            updates.append("got_reply=?")
            values.append(1 if body.got_reply else 0)
        if body.won is not None:
            updates.append("won=?")
            values.append(1 if body.won else 0)
        values.append(pid)
        db.execute(f"UPDATE proposals SET {', '.join(updates)} WHERE id=?", values)
        row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@router.post("/{pid}/work")
def auto_work(pid: int):
    """Have Jarvis attempt to complete the job automatically."""
    with conn() as db:
        row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")

    r = dict(row)
    result = auto_work_job(r["job_title"], r["job_desc"] or "")

    new_status = "done" if result["workable"] else "manual_required"
    now = _now()
    with conn() as db:
        db.execute(
            """UPDATE proposals
               SET work_output=?, work_status=?, status=?, updated_at=?
               WHERE id=?""",
            (result["output"], result["status"], new_status, now, pid),
        )
        updated = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()

    return {
        "proposal": dict(updated),
        "workable": result["workable"],
        "message": (
            "Jarvis completed the work. Review and submit."
            if result["workable"]
            else "This job needs your manual input."
        ),
    }


@router.post("/{pid}/submit")
def mark_submitted(pid: int):
    now = _now()
    with conn() as db:
        db.execute(
            "UPDATE proposals SET status='submitted', updated_at=? WHERE id=?",
            (now, pid),
        )
        row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    return dict(row)


@router.delete("/{pid}")
def delete_proposal(pid: int):
    with conn() as db:
        db.execute("DELETE FROM proposals WHERE id=?", (pid,))
    return {"success": True}
