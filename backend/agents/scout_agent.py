"""
agents/scout_agent.py
ScoutAgent — discovers opportunities across all enabled platforms.
Returns normalized job/task list for ScoreAgent.
"""
import json
from datetime import datetime, timezone
from agents.base_agent import BaseAgent
from models.db import conn


class ScoutAgent(BaseAgent):
    name = "scout"

    def run(self, context: dict) -> dict:
        platforms = context.get("platforms", ["remoteok", "hubstaff", "weworkremotely"])
        max_per   = context.get("max_per_platform", 10)
        all_jobs  = []
        feed      = []

        for platform in platforms:
            self.log(f"Scanning {platform}...")
            jobs = self._scan(platform, max_per)
            feed.append(self.log(f"{platform}: {len(jobs)} opportunities found"))
            all_jobs.extend(jobs)

        # Deduplicate by job_id
        seen, deduped = set(), []
        for j in all_jobs:
            key = j.get("job_id", "")
            if key not in seen:
                seen.add(key)
                deduped.append(j)

        # Persist to platform_jobs
        now = datetime.now(timezone.utc).isoformat()
        saved = 0
        with conn() as db:
            for j in deduped:
                try:
                    db.execute(
                        """INSERT OR IGNORE INTO platform_jobs
                           (job_id,platform,title,description,skills,company,link,budget,date_posted,scraped_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (j.get("job_id"), j.get("platform"), j.get("title"),
                         j.get("description"), json.dumps(j.get("skills", [])),
                         j.get("company",""), j.get("link",""),
                         j.get("budget",""), j.get("date_posted",""), now)
                    )
                    saved += 1
                except Exception:
                    pass

        feed.append(self.log(f"Scout complete: {len(deduped)} unique, {saved} new saved"))
        return {"jobs": deduped, "feed": feed, "saved": saved}

    def _scan(self, platform: str, max_jobs: int) -> list:
        try:
            if platform == "hubstaff":
                from platforms.hubstaff import HubstaffPlatform
                return HubstaffPlatform().scan_jobs(max_jobs)
            elif platform == "remoteok":
                from platforms.remoteok import RemoteOKPlatform
                return RemoteOKPlatform().scan_jobs(max_jobs)
            elif platform == "weworkremotely":
                from platforms.weworkremotely import WeWorkRemotelyPlatform
                return WeWorkRemotelyPlatform().scan_jobs(max_jobs)
            elif platform == "wellfound":
                from platforms.wellfound import WellfoundPlatform
                return WellfoundPlatform().scan_jobs(max_jobs)
            elif platform == "peopleperhour":
                from platforms.peopleperhour import PeoplePerHourPlatform
                return PeoplePerHourPlatform().scan_jobs(max_jobs)
            elif platform == "contra":
                from platforms.contra import ContraPlatform
                return ContraPlatform().scan_jobs(max_jobs)
            elif platform == "clickworker":
                from services.clickworker_service import fetch_public_tasks
                tasks = fetch_public_tasks(max_jobs)
                for t in tasks:
                    t["job_id"]  = t.get("task_id", "")
                    t["link"]    = "https://www.clickworker.com"
                    t["company"] = "Clickworker"
                return tasks
            elif platform == "zuodao":
                from services.zuodao_service import fetch_tasks
                tasks = fetch_tasks(max_jobs)
                for t in tasks:
                    t["job_id"]  = t.get("task_id", "")
                    t["link"]    = t.get("link", "https://www.zuodao.com")
                    t["company"] = "Zuodao"
                return tasks
        except Exception as e:
            self.log(f"_scan({platform}) error: {e}", "error")
        return []
