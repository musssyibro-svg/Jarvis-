"""
routes/messages.py
Freelancer inbox monitoring + reply drafts.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from models.db import conn
from services.deepseek_service import generate_reply_draft

router = APIRouter()


class ReplyRequest(BaseModel):
    message_id: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/sync")
async def sync_inbox(background_tasks: BackgroundTasks):
    """Trigger a background browser scan of the Freelancer inbox."""
    def _do_sync():
        try:
            from services.browser_monitor import sync_inbox_to_db
            count = sync_inbox_to_db()
            print(f"[Sync] Saved {count} new messages")
        except Exception as exc:
            print(f"[Sync] Error: {exc}")

    background_tasks.add_task(_do_sync)
    return {"message": "Inbox sync started in background"}


@router.get("/")
def list_messages(unread_only: bool = False, limit: int = 50):
    with conn() as db:
        if unread_only:
            rows = db.execute(
                "SELECT * FROM messages WHERE is_read=0 ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return {"messages": [dict(r) for r in rows]}


@router.get("/{mid}")
def get_message(mid: int):
    with conn() as db:
        row = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    if not row:
        raise HTTPException(404, "Message not found")
    return dict(row)


@router.post("/{mid}/mark-read")
def mark_read(mid: int):
    with conn() as db:
        db.execute("UPDATE messages SET is_read=1 WHERE id=?", (mid,))
        row = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    return dict(row)


@router.post("/{mid}/regenerate-reply")
def regenerate_reply(mid: int):
    """Regenerate the reply draft for a message."""
    with conn() as db:
        row = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    if not row:
        raise HTTPException(404, "Message not found")
    r = dict(row)
    draft = generate_reply_draft(r["sender"], r["full_message"] or r["message_preview"])
    with conn() as db:
        db.execute("UPDATE messages SET reply_draft=? WHERE id=?", (draft, mid))
    return {"id": mid, "reply_draft": draft}


@router.delete("/{mid}")
def delete_message(mid: int):
    with conn() as db:
        db.execute("DELETE FROM messages WHERE id=?", (mid,))
    return {"success": True}
