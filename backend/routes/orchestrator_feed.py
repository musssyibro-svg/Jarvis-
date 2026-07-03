"""backend/routes/orchestrator_feed.py — SSE feed of orchestrator state.

Consumes the EXISTING STATE event system (agents.orchestrator._State), which
already has subscribe()/unsubscribe()/_listeners. No parallel queue, no emit
patch required — every STATE.emit(agent,msg,level) already fans out to listeners.
We add a 'state' field inferred from the message so the UI core can react.
"""
import json, asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from agents.orchestrator import STATE

router = APIRouter()

_KW = [("approval","approval"),("approve","approval"),("scout","scouting"),
       ("scan","scouting"),("propos","proposing"),("draft","proposing"),
       ("execut","executing"),("submit","executing"),("click","executing"),
       ("plan","thinking"),("decompos","thinking"),("complete","speaking"),
       ("finish","speaking"),("fail","approval"),("error","approval")]

def _infer(agent, msg):
    blob = f"{agent} {msg}".lower()
    for kw, st in _KW:
        if kw in blob:
            return st
    return "thinking"

def _sse(d): return f"data: {json.dumps(d)}\n\n"

@router.get("/orchestrator/sse")
async def orchestrator_feed(request: Request):
    q = STATE.subscribe()           # reuse the real event bus
    async def _stream():
        yield _sse({"ping": True})
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = q.get_nowait()
                    if "state" not in entry:
                        entry = {**entry, "state": _infer(entry.get("agent",""), entry.get("msg",""))}
                    yield _sse(entry)
                except Exception:
                    await asyncio.sleep(0.4)
                    yield _sse({"ping": True})
        finally:
            STATE.unsubscribe(q)
    return StreamingResponse(_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
