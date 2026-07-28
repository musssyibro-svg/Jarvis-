"""
routes/os_console.py — the operating console's data surface.

GET  /os/state        one live snapshot of everything (replaces 6+ separate polls)
GET  /os/traces       recent request traces (exact execution path per request)
GET  /os/traces/{id}  one trace in full
GET  /os/diagnostics  health of the routing itself: failures + worst component
GET  /os/experience   what Jarvis has learned about this machine's apps/failures
POST /os/confidence   how likely a plan is to work, before running it
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

router = APIRouter()


class _Plan(BaseModel):
    steps: list = []


@router.get("/health-check")
def deep_health():
    """Full diagnosis: every dependency, model and binary, with the exact fix."""
    from services.diagnostics import deep_check
    return deep_check()


@router.get("/report", response_class=PlainTextResponse)
def runtime_report():
    """
    Downloadable runtime report — diagnosis + live state + activity + execution
    traces + log tail in one file. This is the thing to send when something
    misbehaves; it contains everything needed to debug it.
    """
    from services.diagnostics import build_report
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return PlainTextResponse(
        build_report(),
        headers={"Content-Disposition": f'attachment; filename="jarvis-report-{stamp}.txt"'})


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


@router.get("/control")
def control_status():
    """Is Jarvis running, pausing, paused or cancelling?"""
    from services import control
    return control.status()


@router.post("/control/{command}")
def control_command(command: str, body: dict | None = None):
    """
    pause / resume / cancel / clear.

    None of these kill anything mid-action: the step in flight always finishes
    first. Interrupting a bid submission halfway would leave a half-filled form
    on a real freelance site.
    """
    from services import control
    reason = (body or {}).get("reason", "")
    fn = {"pause": lambda: control.pause(reason),
          "resume": control.resume,
          "cancel": lambda: control.cancel(reason),
          "clear": control.clear}.get(command)
    if not fn:
        raise HTTPException(400, "command must be pause, resume, cancel or clear")
    return fn()


@router.get("/explain")
def explain(limit: int = 6):
    """
    "Why are you doing this?" — answered from the execution trace and live
    state, not by asking a model to narrate its own behaviour. A model asked to
    explain itself writes a plausible story whether or not it matches what the
    code did, which is worse than no explanation because it convinces.
    """
    from services import control
    return control.explain(limit)


@router.get("/experience")
def os_experience(limit: int = 8):
    """
    What Jarvis has learned by doing: per-app success rates, how long each app
    really takes to open on THIS machine, and the actual causes of recent
    failures (with the fix for each) instead of raw error strings.
    """
    from services import experience
    return experience.summary(limit)


@router.post("/confidence")
def os_confidence(plan: _Plan):
    """Score a plan against real history before spending time on it."""
    from services import experience
    return experience.confidence(plan.steps)


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
