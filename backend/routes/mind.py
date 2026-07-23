"""
routes/mind.py — the Brain layer's read surface.

GET /brain/state          — unified snapshot (world + capabilities + events + reflections)
GET /brain/capabilities   — what Jarvis can do, with availability
POST /brain/route         — {goal} -> best capability + model to use
GET /world/snapshot       — live world model
GET /world/summary        — one-line natural-language state
GET /events/recent        — recent internal events (optionally ?prefix=app.)
GET /brain/reflections    — recent lessons learned
GET /router/status        — model routing per task class
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class RouteIn(BaseModel):
    goal: str


@router.get("/brain/state")
def brain_state():
    from services import brain_core
    return brain_core.state()


@router.get("/brain/capabilities")
def brain_capabilities():
    from services import capability_registry
    return {"capabilities": capability_registry.list_dicts(),
            "describe": capability_registry.describe()}


@router.post("/brain/route")
def brain_route(body: RouteIn):
    from services import brain_core
    return brain_core.route(body.goal)


@router.get("/brain/reflections")
def brain_reflections(limit: int = 10):
    from services import reflection
    return {"reflections": reflection.recent(limit)}


@router.get("/world/snapshot")
def world_snapshot(fast: bool = True):
    from services import world_model
    return world_model.snapshot(fast=fast)


@router.get("/world/summary")
def world_summary():
    from services import world_model
    return {"summary": world_model.summary()}


@router.get("/events/recent")
def events_recent(limit: int = 50, prefix: str = None):
    from services import event_bus
    return {"events": event_bus.recent(limit=limit, prefix=prefix)}


@router.get("/router/status")
def router_status():
    from services import model_router
    return model_router.status()
