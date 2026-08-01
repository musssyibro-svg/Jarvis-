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


@router.get("/providers")
def providers_status():
    """
    What Jarvis will use for each capability on THIS machine, and why.

    "Why did it open Edge?" should have a visible answer before execution, not
    be a surprise afterwards. Override any of these with a provider_<capability>
    setting.
    """
    from services import providers
    return providers.status()


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


@router.get("/environment")
def os_environment(refresh: bool = False):
    """
    What machine is this, really? Browsers, apps, GPU, RAM, language, network,
    models, disk — plus the constraints those facts impose, so behaviour like
    "it used Edge" or "vision is slow" has a stated reason rather than looking
    like a bug.
    """
    from services import environment
    return environment.scan(force=refresh)


@router.get("/persona")
def os_persona():
    """Everything Jarvis knows about you, where each fact came from, what's missing."""
    from services import persona
    return persona.status()


class _Fact(BaseModel):
    field: str
    value: str


@router.post("/persona")
def os_persona_set(fact: _Fact):
    """
    Tell Jarvis something durable. What you state here outranks anything it
    detected, and a later machine scan will not quietly overwrite it.
    """
    from services import persona
    res = persona.remember(fact.field, fact.value, persona.STATED, "set in Settings")
    if not res.get("ok") and not res.get("skipped"):
        raise HTTPException(400, res.get("error", "could not save"))
    return res


@router.delete("/persona/{field}")
def os_persona_forget(field: str):
    from services import persona
    return persona.forget(field)


@router.get("/plan")
def os_plan():
    """The plan that is running right now, step by step, with live status."""
    from services import live_plan
    return live_plan.snapshot()


@router.post("/plan/preview")
def os_plan_preview(body: dict):
    """
    Decompose a command WITHOUT running it — "show me the plan first".
    Also the fastest way to see why a sentence was understood the way it was.
    """
    from services import decompose
    return decompose.preview((body or {}).get("command", ""))


@router.post("/plan/{command}")
def os_plan_control(command: str, body: dict | None = None):
    """
    skip / retry / stop, addressed at a step of the live plan.

    Skip and retry take effect between steps; the step in flight always
    finishes. Stopping a half-typed sentence is worse than finishing it.
    """
    from services import live_plan
    step = int((body or {}).get("step", -1))
    if command == "stop":
        return live_plan.stop((body or {}).get("reason", ""))
    if command not in ("skip", "retry"):
        raise HTTPException(400, "command must be skip, retry or stop")
    if step < 0:
        raise HTTPException(400, "which step? pass {\"step\": <0-based index>}")
    res = getattr(live_plan, command)(step)
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "could not apply"))
    return res


@router.post("/simulate")
def os_simulate(body: dict | None = None):
    """
    "What would you do?" — the full plan, every side effect, a time estimate,
    and anything that would block it. Executes nothing: no window opens, no page
    loads, no proposal is sent.

    Pass {"command": "..."} for a task, or {} for a freelance cycle.
    """
    from services import simulate
    cmd = ((body or {}).get("command") or "").strip()
    return simulate.task(cmd) if cmd else simulate.earning()


@router.get("/why")
def os_why():
    """
    "Why did that happen?" as a chain of real observations — the plan, the code
    path it took, the failure class, and the machine fact behind it. Assembled
    from records, never narrated by a model.
    """
    from services import narrate
    return narrate.why()


@router.get("/why.txt", response_class=PlainTextResponse)
def os_why_text():
    from services import narrate
    return PlainTextResponse(narrate.as_text())


@router.get("/selfeval")
def os_selfeval(limit: int = 10):
    """
    How confident was Jarvis in its recent runs, why, and what it changed about
    itself as a result.
    """
    from services import selfeval
    return selfeval.summary(limit)


@router.get("/teach")
def os_teach_status():
    from services import teach
    return teach.status()


@router.post("/teach/start")
def os_teach_start(body: dict):
    """
    Start watching. Everything you do is recorded as a workflow until you stop —
    except anything typed into a login or password window, which is never
    captured.
    """
    from services import teach
    res = teach.start((body or {}).get("name", ""))
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "could not start recording"))
    return res


@router.post("/teach/stop")
def os_teach_stop(body: dict | None = None):
    """Stop watching and save what was demonstrated as a runnable workflow."""
    from services import teach
    return teach.stop(save=bool((body or {}).get("save", True)))


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
