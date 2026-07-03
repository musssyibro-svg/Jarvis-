"""
platforms/peopleperhour.py
PeoplePerHour — scrapes public project listings.
"""

import re
import traceback

import requests
from bs4 import BeautifulSoup

from platforms.base import BasePlatform

BASE     = "https://www.peopleperhour.com"
JOBS_URL = "https://www.peopleperhour.com/freelance-jobs"
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}


class PeoplePerHourPlatform(BasePlatform):
    name = "peopleperhour"

    def scan_jobs(self, max_jobs: int = 20) -> list[dict]:
        try:
            resp = requests.get(JOBS_URL, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".joblist-item, .project-list-item, [class*='joblist'], article")
            jobs = []
            for i, card in enumerate(cards[:max_jobs]):
                a = card.select_one("a[href*='/job/'], a[href*='/project/'], h2 a, h3 a")
                title_el = card.select_one("h2, h3, .title, [class*='title']")
                title = title_el.get_text(strip=True) if title_el else (a.get_text(strip=True) if a else f"Job #{i+1}")
                href = a["href"] if a and a.get("href") else ""
                link = f"{BASE}{href}" if href.startswith("/") else href
                desc_el = card.select_one("p, .description, [class*='desc']")
                desc = desc_el.get_text(strip=True)[:600] if desc_el else ""
                budget_el = card.select_one(".budget, .price, [class*='budget'], [class*='price']")
                budget = budget_el.get_text(strip=True) if budget_el else ""
                skill_els = card.select(".skill, .tag, [class*='skill'], [class*='tag']")
                skills = [s.get_text(strip=True) for s in skill_els if s.get_text(strip=True)]
                jobs.append({
                    "job_id":      f"pph_{abs(hash(link)) % 999_999}",
                    "title":       title,
                    "description": desc,
                    "skills":      skills[:10],
                    "company":     "",
                    "link":        link,
                    "date_posted": "",
                    "platform":    "peopleperhour",
                    "budget":      budget,
                })
            print(f"[PeoplePerHour] Got {len(jobs)} jobs")
            return jobs
        except Exception as exc:
            traceback.print_exc()
            return []

    def generate_application(self, job: dict, your_name: str = "Ibrahim",
                              your_skills: str = "Python, automation, web scraping, AI integration, FastAPI") -> str:
        from services.deepseek_service import call_model
        prompt = f"""Write a concise PeoplePerHour project proposal.

Project: {job['title']}
Budget: {job.get('budget','not specified')}
Description: {job.get('description','')}

Applicant: {your_name} | Skills: {your_skills}
Under 160 words. Start by proving you understand the problem. 
Propose a solution and timeline. Mention relevant experience. 
Clear CTA. Sign as {your_name}.
Output ONLY the proposal."""
        return call_model(prompt)

    def submit_application(self, job: dict, application_text: str) -> dict:
        return {"submitted": False, "message": f"Apply at {job.get('link')}"}

    def check_replies(self) -> list[dict]:
        return []
