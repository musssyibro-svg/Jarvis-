"""DEPRECATED (V9): responsibilities moved to agents/orchestrator_core.py.
Kept import-safe for backward compatibility; do not extend. Scheduler and routes
now drive OrchestratorCore instead of run_auto_mode()."""
"""
services/automation_engine.py
AUTO MODE — scans all platforms, filters jobs, queues applications.
Runs as background task. Frontend polls /automation/status for progress.
"""

import json
import threading
from datetime import datetime, timezone

_state = {
    "running":    False,
    "enabled":    False,
    "progress":   0,
    "stage":      "idle",
    "log":        [],
    "stats": {
        "jobs_found":    0,
        "apps_queued":   0,
        "tasks_found":   0,
        "last_run":      None,
    }
}
_lock = threading.Lock()


def get_state() -> dict:
    with _lock:
        return dict(_state)


def _log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with _lock:
        _state["log"].append(f"[{ts}] {msg}")
        if len(_state["log"]) > 100:
            _state["log"] = _state["log"][-100:]
    print(f"[AutoMode] {msg}")


def _set(key: str, val):
    with _lock:
        _state[key] = val


def run_auto_mode(platforms: list[str], your_name: str, your_skills: str, max_jobs: int = 10):
    """Main automation loop. Call from background thread."""
    if _state["running"]:
        return
    _set("running", True)
    _set("progress", 0)
    _set("log", [])
    _state["stats"]["jobs_found"] = 0
    _state["stats"]["apps_queued"] = 0
    _state["stats"]["tasks_found"] = 0

    try:
        from models.db import conn

        total_platforms = len(platforms)
        per_step = 80 // max(total_platforms, 1)

        for i, platform_name in enumerate(platforms):
            _set("stage", f"scanning_{platform_name}")
            _log(f"Scanning {platform_name}...")
            _set("progress", 10 + i * per_step)

            jobs = _scan_platform(platform_name, max_jobs)
            if not jobs:
                _log(f"{platform_name}: no jobs found")
                continue

            _log(f"{platform_name}: {len(jobs)} jobs found")
            _state["stats"]["jobs_found"] += len(jobs)

            # Save to platform_jobs table
            now = datetime.now(timezone.utc).isoformat()
            with conn() as db:
                for j in jobs:
                    try:
                        db.execute(
                            """INSERT OR IGNORE INTO platform_jobs
                               (job_id, platform, title, description, skills, company, link, budget, date_posted, scraped_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (j.get("job_id"), platform_name, j.get("title"),
                             j.get("description"), json.dumps(j.get("skills", [])),
                             j.get("company", ""), j.get("link", ""),
                             j.get("budget", ""), j.get("date_posted", ""), now)
                        )
                    except Exception:
                        pass

            # Filter: skip jobs with no description
            quality = [j for j in jobs if len(j.get("description", "")) > 30]
            _log(f"{platform_name}: {len(quality)} quality jobs after filter")

            # Queue applications
            _set("stage", f"generating_applications_{platform_name}")
            _set("progress", 10 + i * per_step + per_step // 2)

            with conn() as db:
                for j in quality[:5]:  # max 5 per platform per run
                    exists = db.execute(
                        "SELECT id FROM automation_queue WHERE job_id=? AND platform=?",
                        (j.get("job_id"), platform_name)
                    ).fetchone()
                    if exists:
                        continue
                    try:
                        app_text = _gen_application(j, platform_name, your_name, your_skills)
                        db.execute(
                            """INSERT INTO automation_queue
                               (platform, job_id, job_title, action, payload, status, created_at)
                               VALUES (?,?,?,?,?,?,?)""",
                            (platform_name, j.get("job_id"), j.get("title"),
                             "apply", json.dumps({"application": app_text, "job": j}),
                             "pending", now)
                        )
                        _state["stats"]["apps_queued"] += 1
                        _log(f"Queued application: {j.get('title', '')[:50]}")
                    except Exception as e:
                        _log(f"Failed to queue {j.get('title','')[:30]}: {e}")

        # Scan microtask platforms
        if "clickworker" in platforms:
            _set("stage", "scanning_clickworker")
            _log("Scanning Clickworker tasks...")
            from services.clickworker_service import fetch_public_tasks
            tasks = fetch_public_tasks(max_tasks=10)
            _state["stats"]["tasks_found"] += len(tasks)
            _log(f"Clickworker: {len(tasks)} tasks found")

        if "zuodao" in platforms:
            _set("stage", "scanning_zuodao")
            _log("Scanning Zuodao tasks...")
            from services.zuodao_service import fetch_tasks
            tasks = fetch_tasks(max_tasks=10)
            _state["stats"]["tasks_found"] += len(tasks)
            _log(f"Zuodao: {len(tasks)} tasks found")

        _state["stats"]["last_run"] = datetime.now(timezone.utc).isoformat()
        _set("stage", "complete")
        _set("progress", 100)
        _log(f"Auto mode complete. Jobs: {_state['stats']['jobs_found']}, Apps queued: {_state['stats']['apps_queued']}")

    except Exception as e:
        _log(f"Auto mode error: {e}")
        _set("stage", "error")
    finally:
        _set("running", False)


def _scan_platform(name: str, max_jobs: int) -> list[dict]:
    try:
        if name == "hubstaff":
            from platforms.hubstaff import HubstaffPlatform
            return HubstaffPlatform().scan_jobs(max_jobs)
        elif name == "remoteok":
            from platforms.remoteok import RemoteOKPlatform
            return RemoteOKPlatform().scan_jobs(max_jobs)
        elif name == "weworkremotely":
            from platforms.weworkremotely import WeWorkRemotelyPlatform
            return WeWorkRemotelyPlatform().scan_jobs(max_jobs)
        elif name == "remoteco":
            from platforms.remoteco import RemoteCoPlatform
            return RemoteCoPlatform().scan_jobs(max_jobs)
        elif name == "wellfound":
            from platforms.wellfound import WellfoundPlatform
            return WellfoundPlatform().scan_jobs(max_jobs)
        elif name == "peopleperhour":
            from platforms.peopleperhour import PeoplePerHourPlatform
            return PeoplePerHourPlatform().scan_jobs(max_jobs)
        elif name == "contra":
            from platforms.contra import ContraPlatform
            return ContraPlatform().scan_jobs(max_jobs)
    except Exception as e:
        print(f"[AutoMode] _scan_platform({name}) error: {e}")
    return []


def _gen_application(job: dict, platform: str, your_name: str, your_skills: str) -> str:
    try:
        from services.deepseek_service import call_model
        return call_model(
            f"""Write a professional job application for {platform}.
Job: {job.get('title')} | Company: {job.get('company','the company')}
Description: {job.get('description','')}
Applicant: {your_name} | Skills: {your_skills}
Under 180 words. Reference the role. Highlight relevant skills. Clear CTA. Sign as {your_name}.
Output ONLY the application message.""",
            fast=True
        )
    except Exception:
        return f"Hi, I am applying for {job.get('title','')}. Please consider my application. — {your_name}"
