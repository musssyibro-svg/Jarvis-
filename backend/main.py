"""main.py — Jarvis OS backend"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("jarvis")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Never proxy localhost.
#
# One review suggested teaching Jarvis to honour HTTP_PROXY. `requests` already
# does that by default — the real hazard here is the opposite one. Anyone behind
# the GFW is running a proxy or 加速器, and with HTTP_PROXY set, calls to
# 127.0.0.1:11434 get sent to that proxy too. Ollama is on this machine, so the
# proxy has no route to it: the model appears offline, Jarvis reports "Ollama
# isn't running" while it plainly is, and no amount of restarting helps.
_no_proxy = os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")
_local = ["127.0.0.1", "localhost", "::1"]
_missing = [h for h in _local if h not in _no_proxy]
if _missing:
    merged = ",".join(filter(None, [_no_proxy] + _missing))
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = merged
CORS_ORIGINS = os.getenv("CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000").split(",")
# Vite moves to 5174, 5175, ... whenever 5173 is already taken (a stale dev
# server from a previous run is enough). The UI then loads fine but every API
# call is blocked by CORS, which shows up as a console that looks connected and
# reports nothing — much harder to diagnose than a page that fails to load.
# Any localhost port is allowed; this server only ever binds to 127.0.0.1.
CORS_LOCALHOST = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

JARVIS_VERSION = "14.0"
app = FastAPI(title="Jarvis OS", version=JARVIS_VERSION, docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_origin_regex=CORS_LOCALHOST,
                   allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*", "X-Jarvis-Token"])


# ── The gate ─────────────────────────────────────────────────────────────────
#
# Jarvis can type on your keyboard and drive a browser already logged into your
# accounts. CORS does not protect that: it governs whether a page may READ the
# response, not whether the request is delivered — a POST that starts typing has
# already done its damage by the time CORS blocks the reply.
#
# So every request is checked before it reaches a route. Defaults are chosen so
# an ordinary local run needs no configuration: see services/auth.py.
#
# WRITTEN AS RAW ASGI, DELIBERATELY.
#
# The obvious version is @app.middleware("http"), which is Starlette's
# BaseHTTPMiddleware. That wrapper consumes the response body through an
# anyio task pair, and it is a long-standing trap for STREAMING responses:
# /orchestrator/feed is an SSE stream that never ends, and the console
# reconnects to it every few seconds. Each of those connections would sit
# inside a middleware task for as long as it lived, and reconnect churn piles
# them up until ordinary requests start to stall — which the UI then reports
# as "Backend offline" while the backend is demonstrably up and working.
#
# Raw ASGI middleware forwards send/receive untouched, so a stream is a stream.
class _Gate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)   # websockets, lifespan
        if scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)   # preflight acts on nothing

        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        try:
            from services import auth
            allowed, code, message = auth.authorize(
                scope.get("path", ""), scope.get("method", "GET"), headers)
        except Exception:
            allowed = True          # never lock the user out because of a bug here

        if allowed:
            return await self.app(scope, receive, send)

        logger.warning(f"blocked {scope.get('method')} {scope.get('path')}: {message}")
        body = json.dumps({"error": message, "blocked_by": "jarvis-auth"}).encode()
        # CORS headers by hand: this response never reaches CORSMiddleware, and
        # without them the browser reports an opaque CORS failure instead of the
        # explanation above — hiding the very message that says what to do.
        origin = headers.get("origin", "")
        out = [(b"content-type", b"application/json")]
        if origin:
            out += [(b"access-control-allow-origin", origin.encode()),
                    (b"access-control-allow-credentials", b"true")]
        await send({"type": "http.response.start", "status": code, "headers": out})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(_Gate)


@app.get("/auth/status", tags=["Auth"])
def auth_status():
    """What is protecting this instance right now. Never returns the token."""
    from services import auth
    return auth.status()


from models.db import conn, init_db


@app.on_event("startup")
def _startup():
    logger.info(f"Jarvis OS v{JARVIS_VERSION} starting...")
    init_db()
    # V5: init extra tables for agents, memory, plans
    try:
        from models.db import init_v5
        with conn() as db:
            init_v5(db)
        logger.info("V5 agent tables ready.")
    except Exception as e:
        logger.warning(f"V5 schema: {e}")
    try:
        from services.brain_service import init_brain
        init_brain()
        logger.info("Brain tables ready.")
    except Exception as e:
        logger.warning(f"Brain schema: {e}")
    try:
        from services.planner_service import init_planner
        init_planner()
        logger.info("Planner tables ready.")
    except Exception as e:
        logger.warning(f"Planner schema: {e}")
    try:
        from services.pulse_service import init_pulse, start_pulse
        init_pulse()
        start_pulse()   # proactive heartbeat: briefing + plan/job/system nudges
        logger.info("Pulse (proactive engine) running.")
    except Exception as e:
        logger.warning(f"Pulse init: {e}")
    try:
        from services.vault import init_vault
        init_vault()
        logger.info("Credential vault ready.")
    except Exception as e:
        logger.warning(f"Vault init: {e}")
    try:
        from agents.registry import load_custom_agents
        n = load_custom_agents()
        logger.info(f"Custom agents loaded: {n}")
    except Exception as e:
        logger.warning(f"Custom agent load: {e}")
    try:
        from services.session_manager import start_reply_monitor
        start_reply_monitor()   # inbox sweeps (opt-in via monitor_inbox setting)
        logger.info("Reply monitor armed.")
    except Exception as e:
        logger.warning(f"Reply monitor: {e}")
    try:
        from services.planner_service import start_watchdog
        start_watchdog()        # auto-complete plans + recover stalled steps
    except Exception as e:
        logger.warning(f"Plan watchdog: {e}")
    try:
        from services.workflow_service import init_workflows
        init_workflows()        # learned/replayable tasks
        logger.info("Workflow store ready.")
    except Exception as e:
        logger.warning(f"Workflow init: {e}")
    try:
        from services.app_resolver import init_app_paths
        init_app_paths()        # remembered executable paths (qq/doubao/wechat)
    except Exception as e:
        logger.warning(f"App-path store init: {e}")
    try:
        from services.custom_platforms import _register_with_session_manager, init_custom_platforms
        init_custom_platforms()
        _register_with_session_manager()   # user-added freelance sites become first-class
        logger.info("Custom platforms ready.")
    except Exception as e:
        logger.warning(f"Custom platforms init: {e}")
    try:
        from services.platform_health import init_health
        init_health()          # per-site reliability, backoff + auto-pause
    except Exception as e:
        logger.warning(f"Platform health init: {e}")
    try:
        from services.maintenance import start as start_maintenance
        start_maintenance()    # 24/7 hygiene: checkpoint, prune, vacuum, unload
    except Exception as e:
        logger.warning(f"Maintenance init: {e}")
    try:
        from services import model_router
        st = model_router.status()
        logger.info(f"Model router: {st['picks']['chat'].get('model')} for chat "
                    f"({st['free_ram_gb']}GB free)")
        for w in st.get("warnings", []):
            logger.warning(f"Model router: {w}")
    except Exception as e:
        logger.warning(f"Model router init: {e}")
    try:
        # Look at the machine BEFORE deciding anything, then record what that
        # implies about the user. Both run in background threads: a slow WMI
        # call must not delay the port opening.
        from services import environment, persona
        environment.start()
        persona.start()
        logger.info("Environment scan started; persona will seed from it.")
    except Exception as e:
        logger.warning(f"Environment/persona init: {e}")
    try:
        from services import auth
        st = auth.status()
        logger.info(f"Security: {st['summary']}")
        if st["token_required"]:
            logger.info(f"Token required — it is in {auth.TOKEN_FILE}")
    except Exception as e:
        logger.warning(f"Auth init: {e}")
    try:
        from services.brain_core import start as start_brain
        start_brain()           # world model sensing + event-first proactive loop
        logger.info("Brain online (world model + event bus).")
    except Exception as e:
        logger.warning(f"Brain init: {e}")
    try:
        from services.income_engine import start_watchdog as start_income
        start_income()          # resume the always-on income engine if it was enabled
        logger.info("Income engine armed.")
    except Exception as e:
        logger.warning(f"Income engine: {e}")
    logger.info("Database ready.")

# ── Routers ──────────────────────────────────────────────────────────────────
from routes.agents import router as agents_router  # V5
from routes.analytics import router as analytics_router
from routes.automation import router as automation_router
from routes.brain import router as brain_router  # V10 Brain
from routes.clickworker import router as clickworker_router
from routes.fiverr import router as fiverr_router
from routes.hubstaff import router as hubstaff_router
from routes.messages import router as messages_router
from routes.mind import router as mind_router  # V14 Brain / World / Capabilities
from routes.orchestrator import router as orchestrator_router
from routes.orchestrator_feed import router as orchestrator_feed_router
from routes.os_console import router as os_router  # V15 OS console (unified state)
from routes.planner import router as planner_router  # V10 Planner
from routes.proposals import router as proposals_router
from routes.pulse import router as pulse_router  # V11 Pulse
from routes.scraper import router as scraper_router
from routes.sessions import router as sessions_router  # V12 login sessions + vault
from routes.system import router as system_router  # V10 Doctor
from routes.workflows import router as workflows_router  # V13 learned workflows
from routes.zuodao import router as zuodao_router

app.include_router(orchestrator_router, prefix="/orchestrator",  tags=["Orchestrator"])
app.include_router(agents_router,       prefix="/agents",        tags=["Agents"])      # V5
app.include_router(proposals_router,    prefix="/proposals",     tags=["Proposals"])
app.include_router(messages_router,     prefix="/messages",      tags=["Messages"])
app.include_router(analytics_router,    prefix="/analytics",     tags=["Analytics"])
app.include_router(scraper_router,      prefix="/scraper",       tags=["Scraper"])
app.include_router(fiverr_router,       prefix="/fiverr",        tags=["Fiverr"])
app.include_router(hubstaff_router,     prefix="/hubstaff",      tags=["Hubstaff"])
app.include_router(clickworker_router,  prefix="/clickworker",   tags=["Clickworker"])
app.include_router(zuodao_router,       prefix="/zuodao",        tags=["Zuodao"])
app.include_router(automation_router,   prefix="/automation",    tags=["Automation"])
app.include_router(orchestrator_feed_router, tags=["Orchestrator"])
app.include_router(brain_router,        prefix="/brain",         tags=["Brain"])       # V10
app.include_router(planner_router,      prefix="/planner",       tags=["Planner"])     # V10
app.include_router(system_router,       prefix="/system",        tags=["System"])      # V10
app.include_router(pulse_router,        prefix="/pulse",         tags=["Pulse"])       # V11
app.include_router(sessions_router,     prefix="/sessions",      tags=["Sessions"])    # V12
app.include_router(workflows_router,    prefix="/workflows",     tags=["Workflows"])   # V13
app.include_router(mind_router,                                  tags=["Brain"])       # V14 (paths self-prefixed)
app.include_router(os_router,           prefix="/os",            tags=["OS Console"])  # V15

from services.deepseek_service import LLM_PROVIDER, OLLAMA_MODEL


class ChatIn(BaseModel):
    message: str; session_id: str = "default"
class TaskIn(BaseModel):
    title: str; note: str = ""
class NoteIn(BaseModel):
    title: str; body: str = ""
class SettingIn(BaseModel):
    value: str

def _now(): return datetime.now(timezone.utc).isoformat()

def _save_msg(sid, role, content):
    with conn() as db:
        db.execute("INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                   (sid, role, content, _now()))

def _get_history(sid, limit=12):
    with conn() as db:
        rows = db.execute(
            "SELECT role,content FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (sid, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

def _sse(chunk="", done=False):
    return f"data: {json.dumps({'chunk': chunk, 'done': done})}\n\n"

@app.get("/")
def root(): return {"app": "Jarvis OS", "version": JARVIS_VERSION, "running": True, "docs": "/api/docs"}

@app.get("/health")
def health():
    ollama_ok = False
    try:
        import ollama as _ol; _ol.list(); ollama_ok = True
    except Exception: pass
    return {
        "status":    "online",
        "version":   JARVIS_VERSION,
        "provider":  LLM_PROVIDER,
        "ollama":    ollama_ok,
        "ollama_ok": ollama_ok,
        "model":     OLLAMA_MODEL,
    }

@app.get("/stats")
def stats():
    try:
        disk = "C:\\" if os.name == "nt" else "/"
        # interval=None is non-blocking (reads since the last call) — the old
        # 0.3s blocking sample ran on every dashboard poll and wasted CPU.
        return {"cpu": psutil.cpu_percent(interval=None),
                "ram": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage(disk).percent}
    except Exception: return {"cpu": 0, "ram": 0, "disk": 0}

@app.post("/chat")
def chat(body: ChatIn):
    if not body.message.strip(): raise HTTPException(400, "Empty message")
    _save_msg(body.session_id, "user", body.message)
    # V8.5: Chat is the single entry point — route through Commander, which
    # detects intent and dispatches to the right agent (desktop/vision/plan/
    # freelance) or falls back to plain chat. Commander emits to the SSE feed.
    try:
        from adapters.commander_adapter import handle_chat
        result   = handle_chat(body.message, body.session_id)
        reply    = result.get("response", "")
        intent   = result.get("intent", "chat")
        data     = result.get("data", {})
        needs_ok = bool(result.get("needs_approval"))
    except Exception as e:
        # Routing failed. DON'T silently pretend it was plain chat — that hid real
        # feature failures and made everything "feel identical". Log loudly, emit
        # to the live feed, and tell the user the feature path errored.
        import traceback
        logger.error(f"handle_chat FAILED for {body.message!r}: {e}\n{traceback.format_exc()}")
        try:
            from agents.orchestrator import STATE
            STATE.emit("commander", f"Routing error: {e}", "error")
        except Exception:
            pass
        reply    = (f"That command hit an error in the feature path (not plain chat): "
                    f"{e}. I'm flagging it instead of pretending it worked.")
        intent, data, needs_ok = "error", {"error": str(e)}, False
    _save_msg(body.session_id, "assistant", reply)
    _maybe_learn(body.session_id)
    return {"response": reply, "intent": intent, "data": data,
            "needs_approval": needs_ok}


LEARN_EVERY = 24  # messages per session between auto-learn rollups

def _maybe_learn(session_id: str):
    """
    Brain Layer 7: every LEARN_EVERY messages in a session, summarize the
    recent slice into the brain in a background thread. Non-blocking,
    best-effort, skips itself when no LLM is installed.
    """
    try:
        with conn() as db:
            n = db.execute("SELECT COUNT(*) AS n FROM chat_messages WHERE session_id=?",
                           (session_id,)).fetchone()["n"]
        if n == 0 or n % LEARN_EVERY != 0:
            return
        history = _get_history(session_id, limit=LEARN_EVERY)
        import threading

        from services.brain_service import learn_from_chat
        threading.Thread(target=learn_from_chat, args=(session_id, history),
                         daemon=True).start()
        logger.info(f"brain: auto-learn triggered for session '{session_id}' ({n} msgs)")
    except Exception as e:
        logger.warning(f"brain auto-learn skipped: {e}")

@app.post("/chat/stream")
def chat_stream(body: ChatIn):
    if not body.message.strip(): raise HTTPException(400, "Empty message")
    history = _get_history(body.session_id)
    _save_msg(body.session_id, "user", body.message)
    def _stream() -> Generator[str, None, None]:
        intent = "chat"
        # Through the router, not straight at Ollama.
        #
        # This used to call ollama.chat() directly with a module-level model
        # name, which meant it ignored the RAM-aware model choice, ignored the
        # token and context caps that stop a small model rambling for minutes,
        # and ignored every fallback the rest of Jarvis has. It was also the
        # one place a provider change would have been silently missed.
        try:
            from services.ai_router import ask_stream
            from services.deepseek_service import SYSTEM_PROMPT
            full = ""
            for chunk in ask_stream(task="chat", prompt=body.message,
                                    history=history, system_prompt=SYSTEM_PROMPT):
                if chunk:
                    full += chunk
                    yield _sse(chunk)
            _save_msg(body.session_id, "assistant", full)
        except Exception as e:
            # Streaming itself broke. Say so rather than going quiet — a stream
            # that stops with no message is indistinguishable from a hang.
            reply = f"[Streaming failed: {e}]"
            _save_msg(body.session_id, "assistant", reply)
            yield _sse(reply)
        # FIX 2: exactly ONE final packet per stream, carrying intent.
        yield f"data: {json.dumps({'chunk': '', 'intent': intent, 'done': True})}\n\n"
        return
    return StreamingResponse(_stream(), media_type="text/event-stream")

@app.get("/chat/history/{session_id}")
def chat_history(session_id: str):
    return {"messages": _get_history(session_id, limit=50)}

@app.post("/memory/clear/{session_id}")
def clear_memory(session_id: str):
    with conn() as db: db.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
    return {"success": True}

@app.get("/tasks")
def get_tasks():
    with conn() as db: rows = db.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
    return {"tasks": [dict(r) for r in rows]}
@app.post("/tasks")
def add_task(t: TaskIn):
    with conn() as db: db.execute("INSERT INTO tasks(title,note,created_at) VALUES(?,?,?)",(t.title,t.note,_now()))
    return {"success": True}
@app.put("/tasks/{tid}/done")
def done_task(tid: int):
    with conn() as db: db.execute("UPDATE tasks SET done=1 WHERE id=?",(tid,))
    return {"success": True}
@app.delete("/tasks/{tid}")
def del_task(tid: int):
    with conn() as db: db.execute("DELETE FROM tasks WHERE id=?",(tid,))
    return {"success": True}

@app.get("/notes")
def get_notes():
    with conn() as db: rows = db.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    return {"notes": [dict(r) for r in rows]}
@app.post("/notes")
def add_note(n: NoteIn):
    with conn() as db: db.execute("INSERT INTO notes(title,body,created_at) VALUES(?,?,?)",(n.title,n.body,_now()))
    return {"success": True}
@app.delete("/notes/{nid}")
def del_note(nid: int):
    with conn() as db: db.execute("DELETE FROM notes WHERE id=?",(nid,))
    return {"success": True}

@app.get("/settings")
def get_settings():
    with conn() as db: rows = db.execute("SELECT * FROM settings").fetchall()
    return {"settings": [dict(r) for r in rows]}
@app.post("/settings/{key}")
def save_setting(key: str, p: SettingIn):
    """
    Save a setting and make it take effect immediately.

    Goes through services.config rather than writing the row directly, because
    a bare INSERT was the whole bug: the value landed in the table and nothing
    ever read it, so the UI said "saved" while the running system carried on
    with the old value. config.set() also drops the read cache and mirrors the
    value into the environment, so the very next request sees it.
    """
    from services import config
    res = config.set(key, p.value)
    if not res.get("ok"):
        raise HTTPException(500, res.get("error", "could not save"))
    return {"success": True, **res}


@app.get("/settings/effective")
def effective_settings():
    """
    Every setting, its live value, and WHERE that value came from.

    This is the answer to "I set it and nothing happened" — it shows whether
    the running system actually agrees with what you chose, or is still using
    an environment variable or a built-in default.
    """
    from services import config
    return {"settings": config.effective()}


# ── V9: goal-driven orchestrator entry point ─────────────────────────────────
@app.post("/v9/goal")
def v9_goal(body: ChatIn):
    """Convert chat -> typed Goal -> run the OrchestratorCore state machine."""
    from agents.commander import normalize_goal
    from agents.orchestrator_core import OrchestratorCore
    goal = normalize_goal(body.message, body.session_id)
    core = OrchestratorCore()
    core.set_goal(goal)
    snapshot = core.run_full_workflow()
    return {"goal": goal.to_dict(), "result": snapshot}

@app.get("/v9/state")
def v9_state():
    # get_core(), not the module-level `core` name — routes used to run their
    # work on throwaway instances, so this reported IDLE during a live run.
    from agents.orchestrator_core import get_core
    return get_core().snapshot()


# V9: register core agents in the registry (lookup hooks; no behavior change)
try:
    from agents.registry import register_core_agents
    register_core_agents()
except Exception as _e:
    logger.warning(f"Agent registry init failed (non-fatal): {_e}")


# ── Running this file directly ───────────────────────────────────────────────
# `python main.py` is the obvious thing to type, and until now it did nothing
# visible: the module imported, defined `app`, and exited without ever serving.
# That looks exactly like a crash with no error, which is a miserable thing to
# debug. It now starts the server, same as the launcher does.
if __name__ == "__main__":
    import sys

    if Path.cwd() != BASE_DIR:
        # Imports here are relative to backend/, so running from the repo root
        # fails with a confusing ModuleNotFoundError instead of saying why.
        print(f"[!] Run this from the backend folder:\n"
              f"      cd /d {BASE_DIR}\n      python main.py\n")
    try:
        import uvicorn
    except ImportError:
        print("[X] uvicorn is not installed.\n"
              "    pip install -r requirements.txt")
        sys.exit(1)

    port = int(os.getenv("JARVIS_PORT", "8000"))
    print(f"\n  Jarvis backend  ->  http://127.0.0.1:{port}")
    print(f"  API docs        ->  http://127.0.0.1:{port}/api/docs")
    print("  Ctrl+C to stop.\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
