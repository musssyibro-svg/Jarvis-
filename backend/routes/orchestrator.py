"""
routes/orchestrator.py
Orchestrator API + SSE live feed endpoint.
"""
import json
import queue as _queue
from typing import List, Optional
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class PipelineRequest(BaseModel):
    platforms:         List[str] = ["remoteok", "weworkremotely", "hubstaff"]
    your_name:         str       = "Ibrahim"
    your_skills:       str       = "Python, automation, web scraping, AI integration, FastAPI"
    max_per_platform:  int       = 10
    min_score:         int       = 30
    max_generate:      int       = 5
    headless:          bool      = True


@router.post("/start")
def start_pipeline(req: PipelineRequest):
    """
    V9: collapsed into OrchestratorCore (single source of workflow state).
    The legacy agents.orchestrator.start_pipeline thread-pipeline is no longer
    invoked. STATE (the SSE feed) in agents.orchestrator is preserved and reused.
    """
    from agents.v9_models import Goal
    from agents.orchestrator_core import OrchestratorCore
    goal = Goal(
        goal_type="freelance_application",
        objective=f"Pipeline across {', '.join(req.platforms)}",
        constraints={"platforms": req.platforms, "max_jobs": getattr(req, "max_jobs", 5),
                     "auto_apply": False},
        approval_required=True,
        success_condition={"min_applied": 0},
    )
    core = OrchestratorCore()
    core.set_goal(goal)
    import threading
    threading.Thread(target=core.run_full_workflow, daemon=True).start()
    return {"message": "Pipeline started (OrchestratorCore)", "platforms": req.platforms,
            "goal_id": goal.goal_id}


@router.post("/stop")
def stop_pipeline():
    from agents.orchestrator import STATE
    STATE.set(running=False, stage="stopped")
    STATE.emit("orchestrator", "Pipeline stop requested")
    return {"message": "Stop signal sent"}


@router.get("/status")
def pipeline_status():
    from agents.orchestrator import STATE
    return STATE.get()


@router.get("/feed")
def live_feed():
    """SSE endpoint — streams agent events to frontend in real time."""
    from agents.orchestrator import STATE

    def _stream():
        q = STATE.subscribe()
        try:
            # Send backlog first
            current = STATE.get()
            for entry in current.get("feed", [])[-20:]:
                yield f"data: {json.dumps(entry)}\n\n"
            # Stream new events
            while True:
                try:
                    entry = q.get(timeout=25)
                    yield f"data: {json.dumps(entry)}\n\n"
                except _queue.Empty:
                    yield "data: {\"ping\":true}\n\n"  # keep-alive
        except GeneratorExit:
            pass
        finally:
            STATE.unsubscribe(q)

    return StreamingResponse(_stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/memory")
def memory_insights():
    from agents.memory_agent import MemoryAgent
    return MemoryAgent.generate_insights()


@router.get("/memory/patterns")
def memory_patterns():
    from agents.memory_agent import MemoryAgent
    return {"patterns": MemoryAgent.get_win_patterns(limit=50)}


@router.get("/memory/platforms")
def platform_memory():
    from agents.memory_agent import MemoryAgent
    return {"platforms": MemoryAgent.get_platform_scores()}


# ── AutoMode scheduling (V8.5) ────────────────────────────────────────────────

class ScheduleRequest(BaseModel):
    platforms:        List[str] = ["remoteok", "weworkremotely", "hubstaff"]
    your_name:        str = "Ibrahim"
    your_skills:      str = "Python, automation, web scraping, AI integration, FastAPI"
    max_per_platform: int = 10
    min_score:        int = 30
    max_generate:     int = 5
    every_minutes:    int = 60

@router.post("/schedule/start")
def schedule_start(req: ScheduleRequest):
    from agents.scheduler import start_schedule
    config = req.dict()
    every = config.pop("every_minutes", 60)
    return start_schedule(config, every_minutes=every)

@router.post("/schedule/stop")
def schedule_stop():
    from agents.scheduler import stop_schedule
    return stop_schedule()

@router.get("/schedule/status")
def schedule_status():
    from agents.scheduler import get_schedule_status
    return get_schedule_status()
