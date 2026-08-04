"""
platforms/contra.py
Contra — independent work platform. Scrapes public opportunity listings.
"""

import traceback

import requests
from bs4 import BeautifulSoup

from platforms.base import BasePlatform

BASE     = "https://contra.com"
JOBS_URL = "https://contra.com/opportunities"
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


class ContraPlatform(BasePlatform):
    name = "contra"

    def scan_jobs(self, max_jobs: int = 20) -> list[dict]:
        try:
            resp = requests.get(JOBS_URL, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("[class*='OpportunityCard'], [class*='opportunity'], [class*='project-card'], article")
            jobs = []
            for i, card in enumerate(cards[:max_jobs]):
                a = card.select_one("a")
                title_el = card.select_one("h2, h3, [class*='title']")
                title = title_el.get_text(strip=True) if title_el else (a.get_text(strip=True) if a else f"Opportunity #{i+1}")
                href = a["href"] if a and a.get("href") else ""
                link = f"{BASE}{href}" if href.startswith("/") else (href or JOBS_URL)
                desc_el = card.select_one("p, [class*='description']")
                desc = desc_el.get_text(strip=True)[:600] if desc_el else ""
                pay_el = card.select_one("[class*='rate'], [class*='pay'], [class*='budget']")
                budget = pay_el.get_text(strip=True) if pay_el else ""
                skill_els = card.select("[class*='skill'], [class*='tag']")
                skills = [s.get_text(strip=True) for s in skill_els if s.get_text(strip=True)]
                jobs.append({
                    "job_id":      f"contra_{abs(hash(link)) % 999_999}",
                    "title":       title,
                    "description": desc,
                    "skills":      skills[:10],
                    "company":     "",
                    "link":        link,
                    "date_posted": "",
                    "platform":    "contra",
                    "budget":      budget,
                })
            print(f"[Contra] Got {len(jobs)} jobs")
            return jobs
        except Exception:
            traceback.print_exc()
            return []

    def generate_application(self, job: dict, your_name: str = "Ibrahim",
                              your_skills: str = "Python, automation, web scraping, AI integration, FastAPI") -> str:
        from services.deepseek_service import call_model
        prompt = f"""Write an independent freelancer application for a Contra opportunity.

Opportunity: {job['title']}
Rate: {job.get('budget','negotiable')}
Description: {job.get('description','')}

Applicant: {your_name} | Skills: {your_skills}
Under 150 words. Professional but personable tone. Show you work independently.
Highlight relevant skill. Clear CTA. Sign as {your_name}.
Output ONLY the message."""
        return call_model(prompt)

    def submit_application(self, job: dict, application_text: str) -> dict:
        return {"submitted": False, "message": f"Apply at {job.get('link')}"}

    def check_replies(self) -> list[dict]:
        return []
