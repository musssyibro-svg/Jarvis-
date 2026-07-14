"""
routes/pulse.py — read side of the proactive Pulse engine.

GET  /pulse/recent?limit=20&unseen=1  -> stored notifications, newest first
POST /pulse/seen                      -> mark everything seen
POST /pulse/tick                      -> force a probe pass now (debug/manual)
"""
from fastapi import APIRouter

from services import pulse_service as pulse

router = APIRouter()


@router.get("/recent")
def recent(limit: int = 20, unseen: int = 0):
    return {"events": pulse.recent(limit=min(limit, 100), unseen_only=bool(unseen))}


@router.post("/seen")
def seen():
    return {"marked": pulse.mark_seen()}


@router.post("/tick")
def tick():
    pulse.tick()
    return {"ok": True}
