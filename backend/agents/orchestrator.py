"""
agents/orchestrator.py
The central Jarvis orchestrator.
Controls the full pipeline:
  Scout → Score → Proposal → Memory → (Browser on approval)

Uses SSE-compatible event queue for live frontend feed.
Thread-safe state. No race conditions.
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

def run_pipeline(config: dict):
    """
    Main pipeline. Run in a background thread.
    config keys:
      platforms, your_name, your_skills, max_per_platform,
      min_score, max_generate, headless
    """
    if STATE.get()["running"]:
        STATE.emit("orchestrator", "Pipeline already running — skipped")
        return

    STATE.set(running=True, stage="starting", progress=0)
    STATE.emit("orchestrator", f"Pipeline started — platforms: {config.get('platforms')}")

    try:
        # ── 1. SCOUT ────────────────────────────────────────────────────────
        STATE.set(stage="scouting", progress=10)
        STATE.emit("scout", "Scanning platforms for opportunities...")

        from agents.scout_agent import ScoutAgent
        scout_result = ScoutAgent().run({
            "platforms":          config.get("platforms", ["remoteok"]),
            "max_per_platform":   config.get("max_per_platform", 10),
        })
        jobs     = scout_result["jobs"]
        jobs_found = len(jobs)
        STATE.update_stats(jobs_found=jobs_found)

        for e in scout_result.get("feed", []):
            STATE.emit(e["agent"], e["msg"])

        STATE.set(progress=30)

        # ── 2. SCORE ────────────────────────────────────────────────────────
        STATE.set(stage="scoring", progress=35)
        STATE.emit("score", f"Scoring {jobs_found} opportunities...")

        from agents.score_agent import ScoreAgent
        from agents.memory_agent import MemoryAgent
        win_patterns = MemoryAgent.get_win_patterns()
        score_result = ScoreAgent().run({
            "jobs":        jobs,
            "min_score":   config.get("min_score", 30),
            "your_skills": config.get("your_skills", "python automation"),
            "win_patterns": win_patterns,
        })
        qualified = score_result["qualified"]
        STATE.update_stats(jobs_qualified=len(qualified))

        for e in score_result.get("feed", []):
            STATE.emit(e["agent"], e["msg"])

        STATE.emit("score", f"{len(qualified)} jobs qualified for proposals")
        STATE.set(progress=55)

        # ── 3. PROPOSAL ─────────────────────────────────────────────────────
        STATE.set(stage="generating", progress=60)
        STATE.emit("proposal", f"Generating proposals for top {min(len(qualified),config.get('max_generate',5))} jobs...")

        from agents.proposal_agent import ProposalAgent
        proposal_result = ProposalAgent().run({
            "qualified_jobs": qualified,
            "your_name":      config.get("your_name", "Ibrahim"),
            "your_skills":    config.get("your_skills", "Python, automation"),
            "max_generate":   config.get("max_generate", 5),
        })
        generated = proposal_result["generated"]
        STATE.update_stats(proposals_gen=len(generated))

        for e in proposal_result.get("feed", []):
            STATE.emit(e["agent"], e["msg"])

        STATE.set(progress=80)

        # ── 4. MEMORY ───────────────────────────────────────────────────────
        STATE.set(stage="learning", progress=85)
        STATE.emit("memory", "Updating memory from outcomes...")

        memory_result = MemoryAgent().run({})
        insights = memory_result.get("insights", {})

        for e in memory_result.get("feed", []):
            STATE.emit(e["agent"], e["msg"])

        if insights.get("best_platform"):
            STATE.emit("memory", f"Best platform: {insights['best_platform']}")
        if insights.get("top_pattern"):
            STATE.emit("memory", f"Top win keyword: {insights['top_pattern']}")

        STATE.set(progress=95)

        # ── 5. QUEUE FOR APPROVAL ───────────────────────────────────────────
        STATE.set(stage="queueing", progress=98)
        _queue_for_approval(generated)
        STATE.emit("orchestrator", f"Queued {len(generated)} proposals for approval")

        # ── DONE ────────────────────────────────────────────────────────────
        now = datetime.now(timezone.utc).isoformat()
        STATE.update_stats(last_run=now)
        STATE.update_stats(cycles_inc=1)
        STATE.set(stage="complete", progress=100)
        STATE.emit("orchestrator",
                   f"✓ Cycle complete — {jobs_found} found, {len(qualified)} qualified, {len(generated)} proposals generated")

    except Exception as e:
        STATE.set(stage="error")
        STATE.emit("orchestrator", f"Pipeline error: {e}", "error")
    finally:
        STATE.set(running=False)


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


def start_pipeline(config: dict):
    """Start the pipeline in a background daemon thread."""
    t = threading.Thread(target=run_pipeline, args=(config,), daemon=True)
    t.start()
    return t
