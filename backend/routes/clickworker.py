"""routes/clickworker.py"""
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from models.db import conn

router = APIRouter()

def _now(): return datetime.now(timezone.utc).isoformat()

class CompleteIn(BaseModel):
    task_id: str
    title: str
    reward: float = 0.0
    notes: str = ""

class AIAssistIn(BaseModel):
    task_id: str
    title: str
    description: str

@router.post("/fetch")
def fetch_tasks(max_tasks: int = 20):
    from services.clickworker_service import fetch_public_tasks
    tasks = fetch_public_tasks(max_tasks)
    now = _now()
    saved = 0
    with conn() as db:
        for t in tasks:
            try:
                db.execute(
                    """INSERT OR IGNORE INTO clickworker_tasks
                       (task_id,title,category,description,reward,estimated_time,status,fetched_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (t["task_id"],t["title"],t.get("category",""),t.get("description",""),
                     t.get("reward",0.0),t.get("estimated_time",15),"available",now)
                )
                saved += 1
            except Exception: pass
    with conn() as db:
        rows = db.execute("SELECT * FROM clickworker_tasks ORDER BY id DESC LIMIT 100").fetchall()
    return {"tasks": [dict(r) for r in rows], "fetched": len(tasks), "saved": saved}

@router.get("/tasks")
def list_tasks(status: str | None = None):
    with conn() as db:
        if status:
            rows = db.execute("SELECT * FROM clickworker_tasks WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM clickworker_tasks ORDER BY id DESC").fetchall()
    return {"tasks": [dict(r) for r in rows]}

@router.post("/complete")
def mark_complete(body: CompleteIn):
    now = _now()
    with conn() as db:
        db.execute("UPDATE clickworker_tasks SET status='completed' WHERE task_id=?", (body.task_id,))
        db.execute(
            "INSERT INTO clickworker_completed (task_id,title,reward,completed_at,notes) VALUES (?,?,?,?,?)",
            (body.task_id, body.title, body.reward, now, body.notes)
        )
    return {"success": True}

@router.get("/completed")
def list_completed():
    with conn() as db:
        rows = db.execute("SELECT * FROM clickworker_completed ORDER BY id DESC").fetchall()
    total = sum(dict(r)["reward"] for r in rows)
    return {"completed": [dict(r) for r in rows], "total_earned": round(total, 2)}

@router.post("/ai-assist")
def ai_assist(body: AIAssistIn):
    from services.clickworker_service import ai_assist_task
    output = ai_assist_task(body.title, body.description)
    return {"task_id": body.task_id, "ai_output": output}

@router.get("/earnings")
def earnings_report():
    with conn() as db:
        rows = db.execute("SELECT * FROM clickworker_completed").fetchall()
    completed = [dict(r) for r in rows]
    total = sum(r["reward"] for r in completed)
    today = _now()[:10]
    today_earn = sum(r["reward"] for r in completed if (r.get("completed_at") or "")[:10] == today)
    return {"total_earned": round(total,2), "today_earned": round(today_earn,2), "tasks_completed": len(completed)}

@router.delete("/tasks/{tid}")
def delete_task(tid: int):
    with conn() as db:
        db.execute("DELETE FROM clickworker_tasks WHERE id=?", (tid,))
    return {"success": True}
