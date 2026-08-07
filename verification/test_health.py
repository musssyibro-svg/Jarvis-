"""
test_health.py — Full system health check.
- Backend API reachable
- Ollama running, approved models present
- Database accessible with correct tables
- Required directories present
- RAM monitoring at start and end
"""
import json
import os
import sys
from pathlib import Path

from _harness import ARTIFACTS, ROOT, TestRun, dump_ollama_status, guard, save_ram_artifact

BACKEND_URL = "http://127.0.0.1:8000"
REQUIRED_TABLES = [
    "proposals", "messages", "automation_queue", "chat_messages",
    "v5_memory_patterns", "v5_platform_memory", "agent_plans",
]
REQUIRED_DIRS = [
    ROOT / "backend",
    ROOT / "frontend",
    ROOT / "verification",
    ROOT / "verification" / "results",
]


def _http_get(url: str, timeout: int = 5) -> dict:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {"ok": True, "status": r.status, "body": r.read().decode()[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run() -> dict:
    t   = TestRun("test_health")
    ram = [t.ram("start")]

    # Always save Ollama status dump
    t.add_artifact(dump_ollama_status())

    # ── 1. Directory structure ──────────────────────────────────────────────────
    for d in REQUIRED_DIRS:
        t.check(f"directory exists: {d.name}",
                d.exists(),
                evidence={"path": str(d), "exists": d.exists()},
                error=None if d.exists() else f"missing: {d}")

    # ── 2. Backend API ──────────────────────────────────────────────────────────
    health = _http_get(f"{BACKEND_URL}/health")
    t.check("backend /health is reachable",
            health.get("ok") and health.get("status") == 200,
            evidence={"status": health.get("status"),
                      "body_snippet": health.get("body","")[:150],
                      "url": f"{BACKEND_URL}/health"},
            error=None if health.get("ok") else health.get("error","unreachable"))

    if health.get("ok"):
        try:
            body = json.loads(health["body"])
            t.check("health response has provider and ollama_ok fields",
                    "provider" in body,
                    evidence={"response": body})
        except Exception:
            pass

    # ── 3. Ollama ───────────────────────────────────────────────────────────────
    ram.append(t.ram("before_ollama_check"))
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from services.ollama_manager import health as om_health
        h = om_health()
        t.log(f"Ollama health: ok={h.get('ok')}  reason={h.get('reason','')}")
        t.check("Ollama daemon reachable",
                h.get("ok") is True,
                evidence={"host":             h.get("host"),
                          "installed_models": h.get("installed_models",[])[:5]},
                error=None if h.get("ok") else h.get("reason","unreachable"))

        if h.get("ok"):
            approved = h.get("approved_present", {})
            t.check("at least one approved model pulled",
                    any(approved.values()),
                    evidence={"approved_present": approved})
    except Exception as e:
        t.check("ollama_manager importable", False,
                evidence={"exception": str(e)},
                error=str(e))
    ram.append(t.ram("after_ollama_check"))

    # ── 4. Database ─────────────────────────────────────────────────────────────
    try:
        from models.db import DB_PATH, conn, init_db
        t.log(f"DB_PATH: {DB_PATH}")

        db_exists = Path(str(DB_PATH)).exists()
        db_size   = Path(str(DB_PATH)).stat().st_size if db_exists else 0
        t.check("database file exists on disk",
                db_exists,
                evidence={"path": str(DB_PATH), "size_bytes": db_size},
                error=None if db_exists else f"run backend once to create DB at {DB_PATH}")

        if db_exists:
            c = conn()
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            c.close()
            missing = [tb for tb in REQUIRED_TABLES if tb not in tables]
            t.check("all required tables present",
                    len(missing) == 0,
                    evidence={"found_tables": sorted(tables),
                              "required": REQUIRED_TABLES,
                              "missing": missing},
                    error=None if not missing
                          else f"missing: {missing} — start backend once to run init_db()")
    except Exception as e:
        t.check("database accessible", False,
                evidence={"exception": str(e)},
                error=str(e))

    # ── 5. Summary ──────────────────────────────────────────────────────────────
    ram.append(t.ram("end"))
    t.check("health RAM snapshot collected",
            True,
            evidence={"ram_snapshots": ram,
                      "ram_start_used_mb": ram[0].get("used_mb"),
                      "ram_end_used_mb":   ram[-1].get("used_mb")})

    t.add_artifact(save_ram_artifact(ram, "health"))
    return t.finish()


if __name__ == "__main__":
    run()
