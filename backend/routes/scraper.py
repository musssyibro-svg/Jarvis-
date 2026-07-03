"""
routes/scraper.py
Job scanning endpoint. V8.5: aggregates MULTIPLE platforms via ScoutAgent
(Freelancer, RemoteOK, Hubstaff, Clickworker, Zuodao, WeWorkRemotely) instead of
freelancer-only. Existing routes preserved so the frontend keeps working.
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter()

_cache: dict = {"jobs": [], "last_updated": None}
_status: dict = {"running": False, "message": "Idle", "progress": 0}

# Platforms aggregated by the Jobs page (Goal 7).
DEFAULT_PLATFORMS = [
    "freelancer", "remoteok", "hubstaff",
    "clickworker", "zuodao", "weworkremotely",
]


class ScrapeRequest(BaseModel):
    max_jobs: int = 20
    query: str = "python automation scraping"
    platforms: list[str] = DEFAULT_PLATFORMS


def _normalize(job: dict) -> dict:
    """Map any platform's job dict to the required normalized schema."""
    return {
        "id":          job.get("job_id") or job.get("id") or job.get("task_id") or "",
        "title":       job.get("title") or job.get("job_title") or "",
        "platform":    job.get("platform") or job.get("source") or "",
        "budget":      job.get("budget") or job.get("pay") or job.get("reward") or "",
        "description": job.get("description") or job.get("desc") or "",
        "url":         job.get("url") or job.get("link") or "",
        "score":       job.get("score", 0),
    }


def _scout_freelancer(max_jobs: int) -> list:
    """Freelancer isn't a ScoutAgent platform module, so fetch it directly."""
    from services.freelancer_api import scrape_freelancer
    jobs = scrape_freelancer(max_jobs)
    for j in jobs:
        j["platform"] = "freelancer"
    return jobs


def _do_scrape(max_jobs: int, query: str, platforms: list[str]) -> None:
    _status.update(running=True, progress=10, message="Scanning platforms…")
    all_jobs: list[dict] = []
    per_platform = max(3, max_jobs // max(1, len(platforms)))

    try:
        from agents.scout_agent import ScoutAgent
        scout = ScoutAgent()

        # Freelancer handled directly (not a ScoutAgent platform module)
        scout_platforms = []
        for p in platforms:
            if p == "freelancer":
                try:
                    fj = _scout_freelancer(per_platform)
                    print(f"[Scout] platform=freelancer jobs={len(fj)}")
                    all_jobs.extend(fj)
                except Exception as e:
                    print(f"[Scout] platform=freelancer error={e}")
            else:
                scout_platforms.append(p)

        # Remaining platforms via ScoutAgent — one at a time so a single
        # platform failure never aborts the rest (Goal 4).
        for idx, p in enumerate(scout_platforms):
            try:
                jobs = scout._scan(p, per_platform)   # ScoutAgent per-platform scan
                print(f"[Scout] platform={p} jobs={len(jobs)}")
                for j in jobs:
                    j.setdefault("platform", p)
                all_jobs.extend(jobs)
            except Exception as e:
                print(f"[Scout] platform={p} error={e}")
            _status["progress"] = 10 + int(80 * (idx + 1) / max(1, len(scout_platforms)))

        # Normalize + dedupe by (platform, id)
        seen, normalized = set(), []
        for j in all_jobs:
            n = _normalize(j)
            key = (n["platform"], n["id"] or n["title"])
            if key not in seen:
                seen.add(key)
                normalized.append(n)

        _cache["jobs"] = normalized
        _cache["last_updated"] = datetime.utcnow().isoformat()
        plat_counts = {}
        for n in normalized:
            plat_counts[n["platform"]] = plat_counts.get(n["platform"], 0) + 1
        _status.update(
            progress=100,
            message=f"Done. {len(normalized)} jobs across {len(plat_counts)} platform(s): "
                    + ", ".join(f"{k}={v}" for k, v in plat_counts.items()))
    except Exception as exc:
        _status.update(progress=0, message=f"Error: {exc}")
    finally:
        _status["running"] = False


@router.post("/scrape")
async def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    if _status["running"]:
        return {"message": "Scrape already running", "status": _status}
    background_tasks.add_task(_do_scrape, req.max_jobs, req.query, req.platforms)
    return {"message": "Scrape started", "status": _status, "platforms": req.platforms}


@router.get("/jobs")
def get_jobs():
    return {
        "jobs": _cache["jobs"],
        "last_updated": _cache["last_updated"],
        "total": len(_cache["jobs"]),
    }


@router.get("/status")
def scrape_status():
    return _status


@router.delete("/jobs")
def clear_jobs():
    _cache["jobs"] = []
    _cache["last_updated"] = None
    _status.update({"running": False, "message": "Idle", "progress": 0})
    return {"message": "Cleared"}
