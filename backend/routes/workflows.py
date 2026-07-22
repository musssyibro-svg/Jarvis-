"""
routes/workflows.py — saved, replayable tasks ("teach once, run forever").

GET    /workflows               — list saved workflows
POST   /workflows               — teach {name, text?, steps?, description?}
POST   /workflows/{name}/run    — replay through the verified execution engine
DELETE /workflows/{name}        — forget it
POST   /workflows/preview       — {text} -> resolved steps, without saving
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

router = APIRouter()


class TeachIn(BaseModel):
    name: str
    text: str = ""
    steps: list | None = None
    description: str = ""


class PreviewIn(BaseModel):
    text: str


@router.get("")
def list_wf():
    from services.workflow_service import list_workflows
    return {"workflows": list_workflows()}


@router.post("")
def teach_wf(body: TeachIn):
    from services.workflow_service import teach
    r = teach(body.name, body.text, body.steps, body.description)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "failed"))
    return r


@router.post("/preview")
def preview_wf(body: PreviewIn):
    from services.workflow_service import _resolve_to_steps
    return {"steps": _resolve_to_steps(body.text)}


@router.post("/{name}/run")
def run_wf(name: str, background_tasks: BackgroundTasks):
    from services.workflow_service import get, run
    if not get(name):
        raise HTTPException(404, f"no workflow named '{name}'")
    background_tasks.add_task(run, name)
    return {"ok": True, "message": f"Running '{name}' — watch the live feed."}


@router.delete("/{name}")
def delete_wf(name: str):
    from services.workflow_service import delete
    return delete(name)
