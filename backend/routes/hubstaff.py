"""
routes/hubstaff.py
Hubstaff Talent job discovery + application tracking.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from models.db import conn

router = APIRouter()

_scrape_status: dict = {"running": False, "message": "Idle", "count": 0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Models ────────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    max_jobs: int = 20


class ApplicationIn(BaseModel):
    job_id: str
    job_title: str
    company: str = ""
    your_name: str = "Ibrahim"
    your_skills: str = "Python, automation, web scraping, AI integration, FastAPI"


class AppStatusUpdate(BaseModel):
    status: str          # sent | interviewing | rejected | hired
    employer_reply: str | None = None
    got_reply: bool | None = None


# ── Scrape routes ─────────────────────────────────────────────────────────────

@router.post("/scrape")
async def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    if _scrape_status["running"]:
        return {"message": "Scrape already running", "status": _scrape_status}

    def _do():
        from services.hubstaff_service import scrape_hubstaff_jobs
        _scrape_status["running"] = True
        _scrape_status["message"] = "Scraping Hubstaff Talent…"
        try:
            jobs = scrape_hubstaff_jobs(req.max_jobs)
            now = _now()
            saved = 0
            with conn() as db:
                for j in jobs:
                    exists = db.execute(
                        "SELECT id FROM hubstaff_jobs WHERE job_id=?", (j["job_id"],)
                    ).fetchone()
                    if not exists:
                        db.execute(
                            """INSERT INTO hubstaff_jobs
                               (job_id, title, description, skills, company, link, date_posted, scraped_at)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (
                                j["job_id"], j["title"], j["description"],
                                json.dumps(j.get("skills", [])),
                                j.get("company", ""), j.get("link", ""),
                                j.get("date_posted", ""), now,
                            ),
                        )
                        saved += 1
            _scrape_status["message"] = f"Done. {len(jobs)} fetched, {saved} new saved."
            _scrape_status["count"] = len(jobs)
        except Exception as exc:
            _scrape_status["message"] = f"Error: {exc}"
        finally:
            _scrape_status["running"] = False

    background_tasks.add_task(_do)
    return {"message": "Hubstaff scrape started", "status": _scrape_status}


@router.get("/scrape/status")
def scrape_status():
    return _scrape_status


@router.get("/jobs")
def list_jobs(limit: int = 100):
    with conn() as db:
        rows = db.execute(
            "SELECT * FROM hubstaff_jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"jobs": [dict(r) for r in rows]}


@router.delete("/jobs")
def clear_jobs():
    with conn() as db:
        db.execute("DELETE FROM hubstaff_jobs")
    return {"success": True}


# ── Application routes ────────────────────────────────────────────────────────

@router.post("/apply")
def generate_and_save_application(req: ApplicationIn):
    """Generate application message + save application record."""
    with conn() as db:
        job = db.execute(
            "SELECT * FROM hubstaff_jobs WHERE job_id=?", (req.job_id,)
        ).fetchone()

    job_desc = dict(job)["description"] if job else ""

    from services.hubstaff_service import generate_application
    msg = generate_application(
        job_title=req.job_title,
        job_desc=job_desc,
        company=req.company,
        your_name=req.your_name,
        your_skills=req.your_skills,
    )

    now = _now()
    with conn() as db:
        cur = db.execute(
            """INSERT INTO hubstaff_applications
               (job_id, job_title, company, application_msg, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (req.job_id, req.job_title, req.company, msg, "draft", now, now),
        )
        app = db.execute(
            "SELECT * FROM hubstaff_applications WHERE id=?", (cur.lastrowid,)
        ).fetchone()

    return dict(app)


@router.get("/applications")
def list_applications(limit: int = 100):
    with conn() as db:
        rows = db.execute(
            "SELECT * FROM hubstaff_applications ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"applications": [dict(r) for r in rows]}


@router.patch("/applications/{aid}/status")
def update_application_status(aid: int, body: AppStatusUpdate):
    now = _now()
    updates, values = ["status=?", "updated_at=?"], [body.status, now]
    if body.employer_reply is not None:
        updates.append("employer_reply=?"); values.append(body.employer_reply)
    if body.got_reply is not None:
        updates.append("got_reply=?"); values.append(1 if body.got_reply else 0)
    values.append(aid)
    with conn() as db:
        db.execute(f"UPDATE hubstaff_applications SET {', '.join(updates)} WHERE id=?", values)
        row = db.execute("SELECT * FROM hubstaff_applications WHERE id=?", (aid,)).fetchone()
    if not row:
        raise HTTPException(404, "Application not found")
    return dict(row)


@router.delete("/applications/{aid}")
def delete_application(aid: int):
    with conn() as db:
        db.execute("DELETE FROM hubstaff_applications WHERE id=?", (aid,))
    return {"success": True}
