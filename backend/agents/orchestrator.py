"""
agents/orchestrator.py — shared live-state bus (SSE feed) + approval queueing.

The old thread-pipeline that lived here (run_pipeline/start_pipeline) was
superseded by agents/orchestrator_core.py and had no callers left, so it was
removed. What remains is what the whole system genuinely shares:
  * STATE — the thread-safe event/state object every module emits to, which the
    UI streams over /orchestrator/feed.
  * _queue_for_approval — puts generated proposals in front of the human.
"""
import json
import queue
import threading
from datetime import datetime, timezone


# ── Shared state (thread-safe) ───────────────────────────────────────────────

class _State:
    def __init__(self):
        self._lock  = threading.Lock()
        self._data  = {
            "running":   False,
            "stage":     "idle",
            "progress":  0,
            "stats": {
                "jobs_found":    0,
                "jobs_qualified":0,
                "proposals_gen": 0,
                "last_run":      None,
                "cycles":        0,
            },
        }
        self._feed: list[dict] = []
        self._listeners: list[queue.Queue] = []

    def get(self) -> dict:
        with self._lock:
            return {**self._data, "feed": self._feed[-50:]}

    def set(self, **kwargs):
        with self._lock:
            self._data.update(kwargs)

    def update_stats(self, **kwargs):
        """Thread-safe stats update. Use this instead of mutating _data directly."""
        with self._lock:
            self._data.setdefault("stats", {})
            for k, v in kwargs.items():
                if k == "cycles_inc":
                    self._data["stats"]["cycles"] = self._data["stats"].get("cycles", 0) + v
                else:
                    self._data["stats"][k] = v

    def emit(self, agent: str, msg: str, level: str = "info", state: str = None):
        ts    = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = {"ts": ts, "agent": agent, "msg": msg, "level": level}
        if state:
            entry["state"] = state
        # Hold the lock only to mutate _feed and snapshot listeners.
        # Fan out AFTER releasing, so a stalled/misbehaving queue can never
        # block other threads waiting on self._lock (e.g. unsubscribe).
        with self._lock:
            self._feed.append(entry)
            if len(self._feed) > 200:
                self._feed = self._feed[-200:]
            listeners = list(self._listeners)
        for q in listeners:
            try:
                q.put_nowait(entry)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._listeners = [l for l in self._listeners if l is not q]


STATE = _State()


# ── Orchestrator ─────────────────────────────────────────────────────────────

def _queue_for_approval(generated: list):
    from models.db import conn
    now = datetime.now(timezone.utc).isoformat()
    with conn() as db:
        for item in generated:
            exists = db.execute(
                "SELECT id FROM automation_queue WHERE job_id=? AND platform=?",
                (item.get("job_id"), item.get("platform"))
            ).fetchone()
            if not exists:
                db.execute(
                    """INSERT INTO automation_queue
                       (platform,job_id,job_title,action,payload,status,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (item.get("platform"), item.get("job_id"), item.get("job_title"),
                     "apply", json.dumps({"application": item.get("proposal_text",""), "job": item}),
                     "pending", now)
                )
