"""routes/zuodao.py"""
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel
from models.db import conn

router = APIRouter()

def _now(): return datetime.now(timezone.utc).isoformat()

class SubmissionIn(BaseModel):
    task_id: str
    title: str
    output: str

class AIAssistIn(BaseModel):
    task_id: str
    title: str
    description: str

@router.post("/fetch")
def fetch_tasks(max_tasks: int = 20):
    from services.zuodao_service import fetch_tasks
    tasks = fetch_tasks(max_tasks)
    now = _now()
    saved = 0
    with conn() as db:
        for t in tasks:
            try:
                db.execute(
                    """INSERT OR IGNORE INTO zuodao_tasks
                       (task_id,title,category,description,reward,deadline,status,fetched_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (t["task_id"],t["title"],t.get("category",""),t.get("description",""),
                     str(t.get("reward","")),t.get("deadline",""),"available",now)
                )
                saved += 1
            except Exception: pass
    with conn() as db:
        rows = db.execute("SELECT * FROM zuodao_tasks ORDER BY id DESC LIMIT 100").fetchall()
    return {"tasks": [dict(r) for r in rows], "fetched": len(tasks), "saved": saved}

@router.get("/tasks")
def list_tasks(status: str | None = None):
    with conn() as db:
        if status:
            rows = db.execute("SELECT * FROM zuodao_tasks WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM zuodao_tasks ORDER BY id DESC").fetchall()
    return {"tasks": [dict(r) for r in rows]}

@router.post("/submit")
def save_submission(body: SubmissionIn):
    now = _now()
    with conn() as db:
        cur = db.execute(
            "INSERT INTO zuodao_submissions (task_id,title,output,status,created_at) VALUES (?,?,?,?,?)",
            (body.task_id, body.title, body.output, "draft", now)
        )
        row = db.execute("SELECT * FROM zuodao_submissions WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)

@router.get("/submissions")
def list_submissions():
    with conn() as db:
        rows = db.execute("SELECT * FROM zuodao_submissions ORDER BY id DESC").fetchall()
    return {"submissions": [dict(r) for r in rows]}

@router.patch("/submissions/{sid}/status")
def update_submission(sid: int, status: str):
    now = _now()
    with conn() as db:
        db.execute("UPDATE zuodao_submissions SET status=?,submitted_at=? WHERE id=?",
                   (status, now if status == "submitted" else None, sid))
        row = db.execute("SELECT * FROM zuodao_submissions WHERE id=?", (sid,)).fetchone()
    return dict(row)

@router.post("/ai-assist")
def ai_assist(body: AIAssistIn):
    from services.zuodao_service import ai_assist_task
    output = ai_assist_task(body.title, body.description)
    return {"task_id": body.task_id, "ai_output": output}

@router.delete("/tasks/{tid}")
def delete_task(tid: int):
    with conn() as db:
        db.execute("DELETE FROM zuodao_tasks WHERE id=?", (tid,))
    return {"success": True}
