"""
routes/os_console.py — the operating console's data surface.

GET  /os/state        one live snapshot of everything (replaces 6+ separate polls)
GET  /os/traces       recent request traces (exact execution path per request)
GET  /os/traces/{id}  one trace in full
GET  /os/diagnostics  health of the routing itself: failures + worst component
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/state")
def os_state(timeline: int = 40):
    from services.os_state import snapshot
    return snapshot(timeline_limit=timeline)


@router.get("/traces")
def os_traces(limit: int = 20):
    from services import trace
    return {"traces": trace.recent(limit), "summary": trace.summary()}


@router.get("/traces/{trace_id}")
def os_trace(trace_id: str):
    from services import trace
    t = trace.get(trace_id)
    if not t:
        raise HTTPException(404, "trace not found")
    return t


@router.get("/diagnostics")
def os_diagnostics():
    """Is the routing itself healthy? Surfaces silent failures instead of hiding them."""
    from services import trace, capability_registry
    return {
        "traces": trace.summary(),
        "recent": trace.recent(8),
        "capabilities": [{"name": c["name"], "available": c["available"],
                          "missing": c["missing"]}
                         for c in capability_registry.list_dicts()],
    }
