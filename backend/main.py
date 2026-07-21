"""main.py — Jarvis v3 Backend"""
from __future__ import annotations
import json, os, logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

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
CORS_ORIGINS = os.getenv("CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000").split(",")

app = FastAPI(title="Jarvis v3", version="3.0.0", docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

from models.db import conn, init_db

@app.on_event("startup")
def _startup():
    logger.info("Jarvis V5 starting...")
    init_db()
    # V5: init extra tables for agents, memory, plans
    try:
        from models.db import V5_SCHEMA, init_v5
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
        from services.income_engine import start_watchdog as start_income
        start_income()          # resume the always-on income engine if it was enabled
        logger.info("Income engine armed.")
    except Exception as e:
        logger.warning(f"Income engine: {e}")
    logger.info("Database ready.")

# ── Routers ──────────────────────────────────────────────────────────────────
from routes.proposals    import router as proposals_router
from routes.messages     import router as messages_router
from routes.analytics    import router as analytics_router
from routes.scraper      import router as scraper_router
from routes.fiverr       import router as fiverr_router
from routes.hubstaff     import router as hubstaff_router
from routes.clickworker  import router as clickworker_router
from routes.zuodao       import router as zuodao_router
from routes.automation   import router as automation_router
from routes.orchestrator_feed import router as orchestrator_feed_router
from routes.orchestrator import router as orchestrator_router
from routes.agents       import router as agents_router          # V5
from routes.brain        import router as brain_router           # V10 Brain
from routes.planner      import router as planner_router         # V10 Planner
from routes.system       import router as system_router          # V10 Doctor
from routes.pulse        import router as pulse_router           # V11 Pulse
from routes.sessions     import router as sessions_router        # V12 login sessions + vault

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

from services.deepseek_service import call_model, OLLAMA_MODEL, LLM_PROVIDER

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
def root(): return {"app": "Jarvis v3", "running": True, "docs": "/api/docs"}

@app.get("/health")
def health():
    ollama_ok = False
    try:
        import ollama as _ol; _ol.list(); ollama_ok = True
    except Exception: pass
    return {
        "status":    "online",
        "version":   "8.0.0",
        "provider":  LLM_PROVIDER,
        "ollama":    ollama_ok,
        "ollama_ok": ollama_ok,
        "model":     OLLAMA_MODEL,
    }

@app.get("/stats")
def stats():
    try:
        disk = "C:\\" if os.name == "nt" else "/"
        return {"cpu": psutil.cpu_percent(interval=0.3),
                "ram": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage(disk).percent}
    except Exception: return {"cpu": 0, "ram": 0, "disk": 0}

@app.post("/chat")
def chat(body: ChatIn):
    if not body.message.strip(): raise HTTPException(400, "Empty message")
    history = _get_history(body.session_id)
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
        # Never let routing failure break chat — fall back to direct model call
        reply, intent, data, needs_ok = call_model(body.message, history), "chat", {}, False
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
        try:
            import ollama as _ollama
            from services.deepseek_service import SYSTEM_PROMPT
            msgs = [{"role":"system","content":SYSTEM_PROMPT},
                    *history, {"role":"user","content":body.message}]
            full = ""
            for part in _ollama.chat(model=OLLAMA_MODEL, messages=msgs, stream=True):
                chunk = part.get("message",{}).get("content","")
                if chunk: full += chunk; yield _sse(chunk)
            _save_msg(body.session_id, "assistant", full)
        except Exception:
            reply = call_model(body.message, history)
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
    with conn() as db: db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,p.value))
    return {"success": True}


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
    from agents.orchestrator_core import core
    return core.snapshot()


# V9: register core agents in the registry (lookup hooks; no behavior change)
try:
    from agents.registry import register_core_agents
    register_core_agents()
except Exception as _e:
    logger.warning(f"Agent registry init failed (non-fatal): {_e}")
