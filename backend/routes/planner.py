"""
routes/planner.py — Long-term project planner API.

POST   /planner/project              {name, goal, title, auto_steps}  — create/update + auto-decompose
GET    /planner/projects                                              — list all with progress
GET    /planner/project/{name_or_id}                                  — one project + steps
POST   /planner/project/{id}/step    {text, status}                   — add a step
PATCH  /planner/step/{id}            {status, note}                   — update step status
DELETE /planner/step/{id}                                             — remove a step
DELETE /planner/project/{id}                                          — remove a project
POST   /planner/decompose            {goal}                           — preview steps (no save)
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from services import planner_service as planner

router = APIRouter()


class ProjectIn(BaseModel):
    name: str
    goal: str = ""
    title: str = ""
    auto_steps: bool = True


class StepIn(BaseModel):
    text: str
    status: str = "todo"


class StepPatch(BaseModel):
    status: str
    note: str | None = None


class GoalIn(BaseModel):
    goal: str


@router.post("/project")
def create_project(body: ProjectIn):
    r = planner.create_project(body.name, body.goal, body.title, body.auto_steps)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "failed"))
    return r


@router.get("/projects")
def list_projects():
    return {"projects": planner.list_projects()}


@router.get("/project/{name_or_id}")
def get_project(name_or_id: str):
    p = planner.get_project(name_or_id)
    if not p:
        raise HTTPException(404, f"No project '{name_or_id}'")
    return p


@router.post("/project/{project_id}/step")
def add_step(project_id: int, body: StepIn):
    r = planner.add_step(project_id, body.text, body.status)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "failed"))
    return r


@router.patch("/step/{step_id}")
def set_status(step_id: int, body: StepPatch):
    r = planner.set_step_status(step_id, body.status, body.note)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "failed"))
    return r


@router.delete("/step/{step_id}")
def delete_step(step_id: int):
    r = planner.delete_step(step_id)
    if not r.get("ok"):
        raise HTTPException(404, f"No step {step_id}")
    return r


@router.delete("/project/{project_id}")
def delete_project(project_id: int):
    r = planner.delete_project(project_id)
    if not r.get("ok"):
        raise HTTPException(404, f"No project {project_id}")
    return r


@router.post("/decompose")
def decompose(body: GoalIn):
    return {"goal": body.goal, "steps": planner.decompose(body.goal)}


@router.post("/project/{project_id}/execute")
def execute_project(project_id: int, background_tasks: BackgroundTasks):
    """
    AUTO-RUN the project: every todo step is executed (desktop actions) or
    produced (LLM deliverable attached as the step note). Watch the live feed.
    """
    if planner.is_executing(project_id):
        return {"ok": True, "already_running": True}
    p = planner.get_project(project_id)
    if not p:
        raise HTTPException(404, f"No project {project_id}")
    background_tasks.add_task(planner.execute_project, project_id)
    return {"ok": True, "executing": True, "project": p["title"],
            "message": "Auto-execution started — watch the live feed and the "
                       "step notes for results."}


@router.get("/project/{project_id}/executing")
def executing(project_id: int):
    return {"executing": planner.is_executing(project_id)}
