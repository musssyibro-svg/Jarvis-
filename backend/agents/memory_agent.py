"""
backend/agents/memory_agent.py  — Enhanced learning memory (V5)
Stores: proposals, outcomes, patterns, client responses, automation history.
"""
import json
from datetime import datetime, timezone
from models.db import conn


def _now():
    return datetime.now(timezone.utc).isoformat()


class MemoryAgent:

    def run(self, payload=None):
        """
        Orchestrator-compatible entry point.
        Returns {"insights": {...}, "feed": [...]} as the orchestrator expects.
        Safe to call with no args.
        """
        feed = [{"agent": "memory", "msg": "Analyzing stored outcomes and patterns"}]
        try:
            raw = MemoryAgent.generate_insights()
        except Exception as e:
            return {"insights": {}, "feed": feed + [
                {"agent": "memory", "msg": f"Memory analysis skipped: {e}"}]}

        scores = raw.get("stats", []) or []
        best_platform = scores[0]["platform"] if scores else None

        wins = MemoryAgent.get_win_patterns(limit=1)
        top_pattern = None
        if wins:
            snippet = (wins[0].get("proposal_snippet") or "").strip()
            top_pattern = snippet.split()[0] if snippet else None

        insights = {
            "best_platform": best_platform,
            "top_pattern":   top_pattern,
            "advice":        raw.get("insights", []),
            "platform_scores": scores,
        }
        feed.append({"agent": "memory",
                     "msg": f"Memory updated: {len(scores)} platform(s) tracked"})
        return {"insights": insights, "feed": feed}

    @staticmethod
    def record_outcome(platform, job_type, proposal_snippet, won, client_response="", notes=""):
        with conn() as db:
            db.execute(
                "INSERT INTO v5_memory_patterns(platform,job_type,proposal_snippet,won,client_response,notes,created_at) VALUES(?,?,?,?,?,?,?)",
                (platform, job_type, proposal_snippet[:500], 1 if won else 0, client_response[:500], notes, _now())
            )
            existing = db.execute("SELECT * FROM v5_platform_memory WHERE platform=?", (platform,)).fetchone()
            if existing:
                total = existing["total_sent"] + 1
                wins  = existing["total_won"] + (1 if won else 0)
                db.execute("UPDATE v5_platform_memory SET total_sent=?,total_won=?,win_rate=?,last_updated=? WHERE platform=?",
                           (total, wins, round(wins/total*100,1), _now(), platform))
            else:
                db.execute("INSERT INTO v5_platform_memory(platform,total_sent,total_won,win_rate,last_updated) VALUES(?,?,?,?,?)",
                           (platform, 1, 1 if won else 0, 100.0 if won else 0.0, _now()))

    @staticmethod
    def get_win_patterns(platform=None, limit=20):
        with conn() as db:
            if platform:
                rows = db.execute("SELECT * FROM v5_memory_patterns WHERE won=1 AND platform=? ORDER BY id DESC LIMIT ?", (platform,limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM v5_memory_patterns WHERE won=1 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_fail_patterns(limit=20):
        with conn() as db:
            rows = db.execute("SELECT * FROM v5_memory_patterns WHERE won=0 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_platform_scores():
        with conn() as db:
            rows = db.execute("SELECT * FROM v5_platform_memory ORDER BY win_rate DESC").fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def log_action(agent, action, params, result, success):
        with conn() as db:
            db.execute(
                "INSERT INTO automation_history(agent,action,params_json,result_json,success,created_at) VALUES(?,?,?,?,?,?)",
                (agent, action, json.dumps(params)[:1000], json.dumps(result)[:1000], 1 if success else 0, _now())
            )

    @staticmethod
    def get_action_history(agent=None, limit=50):
        with conn() as db:
            if agent:
                rows = db.execute("SELECT * FROM automation_history WHERE agent=? ORDER BY id DESC LIMIT ?", (agent,limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM automation_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def store_client_response(platform, client_name, message, sentiment="neutral"):
        with conn() as db:
            db.execute("INSERT INTO client_responses(platform,client_name,message,sentiment,created_at) VALUES(?,?,?,?,?)",
                       (platform, client_name, message[:1000], sentiment, _now()))

    @staticmethod
    def get_client_responses(client_name=None):
        with conn() as db:
            if client_name:
                rows = db.execute("SELECT * FROM client_responses WHERE client_name=? ORDER BY id DESC LIMIT 20", (client_name,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM client_responses ORDER BY id DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def generate_insights():
        wins  = MemoryAgent.get_win_patterns(limit=10)
        fails = MemoryAgent.get_fail_patterns(limit=10)
        stats = MemoryAgent.get_platform_scores()
        if not wins and not fails:
            return {"insights": ["No memory data yet. Submit proposals to start learning."], "stats": stats}
        try:
            from services.deepseek_service import fast
            prompt = f"""Analyze these freelance proposal outcomes and give 3-5 actionable insights:
WINNING ({len(wins)}): {chr(10).join(w['proposal_snippet'][:100] for w in wins[:5])}
LOSING ({len(fails)}): {chr(10).join(f['proposal_snippet'][:100] for f in fails[:5])}
PLATFORM STATS: {chr(10).join(f"{s['platform']}: {s['win_rate']}% ({s['total_won']}/{s['total_sent']})" for s in stats)}
Give specific actionable advice. Be concise."""
            advice = fast(prompt)
            return {"insights": [l.strip() for l in advice.splitlines() if l.strip()][:6], "stats": stats, "wins": len(wins), "fails": len(fails)}
        except Exception as e:
            return {"insights": [f"AI unavailable: {e}"], "stats": stats}

    @staticmethod
    def store(key, value):
        with conn() as db:
            db.execute("INSERT OR REPLACE INTO memory_kv(key,value,updated_at) VALUES(?,?,?)", (key, value, _now()))

    @staticmethod
    def recall(key):
        with conn() as db:
            row = db.execute("SELECT value FROM memory_kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    @staticmethod
    def get_all_kv():
        with conn() as db:
            rows = db.execute("SELECT key,value,updated_at FROM memory_kv ORDER BY updated_at DESC").fetchall()
        return {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}
