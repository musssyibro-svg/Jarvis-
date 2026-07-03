"""
routes/fiverr.py
Fiverr gig management + inbox monitoring + custom offers.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from models.db import conn

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Models ────────────────────────────────────────────────────────────────────

class GigIn(BaseModel):
    title: str
    category: str = ""
    description: str = ""
    tags: list[str] = []
    pricing: dict = {}
    status: str = "active"


class GigUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    pricing: Optional[dict] = None
    status: Optional[str] = None
    orders: Optional[int] = None
    rating: Optional[float] = None


class OfferRequest(BaseModel):
    message_id: int


# ── Gig routes ────────────────────────────────────────────────────────────────

@router.get("/gigs")
def list_gigs():
    with conn() as db:
        rows = db.execute("SELECT * FROM fiverr_gigs ORDER BY id DESC").fetchall()
    return {"gigs": [dict(r) for r in rows]}


@router.post("/gigs")
def create_gig(gig: GigIn):
    now = _now()
    with conn() as db:
        cur = db.execute(
            """INSERT INTO fiverr_gigs
               (title, category, description, tags, pricing, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                gig.title, gig.category, gig.description,
                json.dumps(gig.tags), json.dumps(gig.pricing),
                gig.status, now, now,
            ),
        )
        row = db.execute("SELECT * FROM fiverr_gigs WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@router.patch("/gigs/{gid}")
def update_gig(gid: int, body: GigUpdate):
    now = _now()
    updates, values = ["updated_at=?"], [now]
    if body.title is not None:       updates.append("title=?");       values.append(body.title)
    if body.category is not None:    updates.append("category=?");    values.append(body.category)
    if body.description is not None: updates.append("description=?"); values.append(body.description)
    if body.tags is not None:        updates.append("tags=?");        values.append(json.dumps(body.tags))
    if body.pricing is not None:     updates.append("pricing=?");     values.append(json.dumps(body.pricing))
    if body.status is not None:      updates.append("status=?");      values.append(body.status)
    if body.orders is not None:      updates.append("orders=?");      values.append(body.orders)
    if body.rating is not None:      updates.append("rating=?");      values.append(body.rating)
    values.append(gid)
    with conn() as db:
        db.execute(f"UPDATE fiverr_gigs SET {', '.join(updates)} WHERE id=?", values)
        row = db.execute("SELECT * FROM fiverr_gigs WHERE id=?", (gid,)).fetchone()
    if not row:
        raise HTTPException(404, "Gig not found")
    return dict(row)


@router.delete("/gigs/{gid}")
def delete_gig(gid: int):
    with conn() as db:
        db.execute("DELETE FROM fiverr_gigs WHERE id=?", (gid,))
    return {"success": True}


# ── Message routes ────────────────────────────────────────────────────────────

@router.post("/sync")
async def sync_inbox(background_tasks: BackgroundTasks):
    def _do():
        try:
            from services.fiverr_service import sync_fiverr_inbox
            count = sync_fiverr_inbox()
            print(f"[Fiverr] Synced {count} new messages")
        except Exception as exc:
            print(f"[Fiverr] Sync error: {exc}")
    background_tasks.add_task(_do)
    return {"message": "Fiverr inbox sync started"}


@router.get("/messages")
def list_messages(unread_only: bool = False, limit: int = 50):
    with conn() as db:
        if unread_only:
            rows = db.execute(
                "SELECT * FROM fiverr_messages WHERE is_read=0 ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM fiverr_messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return {"messages": [dict(r) for r in rows]}


@router.post("/messages/{mid}/mark-read")
def mark_read(mid: int):
    with conn() as db:
        db.execute("UPDATE fiverr_messages SET is_read=1 WHERE id=?", (mid,))
        row = db.execute("SELECT * FROM fiverr_messages WHERE id=?", (mid,)).fetchone()
    return dict(row)


@router.post("/messages/{mid}/regenerate-reply")
def regenerate_reply(mid: int):
    with conn() as db:
        row = db.execute("SELECT * FROM fiverr_messages WHERE id=?", (mid,)).fetchone()
    if not row:
        raise HTTPException(404, "Message not found")
    r = dict(row)
    from services.fiverr_service import _gen_reply
    draft = _gen_reply(r["buyer_name"], r["full_message"] or r["message_preview"])
    with conn() as db:
        db.execute("UPDATE fiverr_messages SET reply_draft=? WHERE id=?", (draft, mid))
    return {"id": mid, "reply_draft": draft}


@router.post("/messages/{mid}/generate-offer")
def generate_offer(mid: int):
    with conn() as db:
        row = db.execute("SELECT * FROM fiverr_messages WHERE id=?", (mid,)).fetchone()
    if not row:
        raise HTTPException(404, "Message not found")
    r = dict(row)
    from services.fiverr_service import generate_custom_offer
    offer = generate_custom_offer(r["buyer_name"], r["full_message"] or r["message_preview"], r["gig_title"] or "")
    with conn() as db:
        db.execute("UPDATE fiverr_messages SET custom_offer=? WHERE id=?", (offer, mid))
    return {"id": mid, "custom_offer": offer}


@router.delete("/messages/{mid}")
def delete_message(mid: int):
    with conn() as db:
        db.execute("DELETE FROM fiverr_messages WHERE id=?", (mid,))
    return {"success": True}
