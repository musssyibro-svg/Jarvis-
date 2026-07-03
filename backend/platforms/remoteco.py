"""
platforms/remoteco.py
Remote.co — scrapes job listings via requests + BeautifulSoup.
"""

import re
import traceback

import requests
from bs4 import BeautifulSoup

from platforms.base import BasePlatform

BASE = "https://remote.co"
JOBS_URL = "https://remote.co/remote-jobs/developer/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}


class RemoteCoPlatform(BasePlatform):
    name = "remoteco"

    def scan_jobs(self, max_jobs: int = 20) -> list[dict]:
        try:
            resp = requests.get(JOBS_URL, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".job_listing, .card, li.job_listing")
            jobs = []
            for i, card in enumerate(cards[:max_jobs]):
                a = card.select_one("a[href*='/remote-jobs/']")
                title_el = card.select_one("h2, h3, .job-title, .position")
                title = title_el.get_text(strip=True) if title_el else (a.get_text(strip=True) if a else f"Job #{i+1}")
                href = a["href"] if a and a.get("href") else ""
                link = f"{BASE}{href}" if href.startswith("/") else href
                company_el = card.select_one(".company, .company_name, [class*='company']")
                company = company_el.get_text(strip=True) if company_el else ""
                date_el = card.select_one("time, .date, [class*='date']")
                date_posted = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""

                # Fetch job page for description
                desc = ""
                if link and link != BASE:
                    try:
                        jr = requests.get(link, headers=HEADERS, timeout=10)
                        jsoup = BeautifulSoup(jr.text, "html.parser")
                        desc_el = jsoup.select_one(".job-description, .description, main")
                        desc = _clean(desc_el.get_text(" "))[:600] if desc_el else ""
                    except Exception:
                        pass

                jobs.append({
                    "job_id":      f"rco_{abs(hash(link)) % 999_999}",
                    "title":       title,
                    "description": desc,
                    "skills":      _extract_skills(desc),
                    "company":     company,
                    "link":        link,
                    "date_posted": str(date_posted)[:10],
                    "platform":    "remoteco",
                })
            print(f"[Remote.co] Got {len(jobs)} jobs")
            return jobs
        except Exception as exc:
            traceback.print_exc()
            return []

    def generate_application(self, job: dict, your_name: str = "Ibrahim",
                              your_skills: str = "Python, automation, web scraping, AI integration, FastAPI") -> str:
        from services.deepseek_service import call_model
        prompt = f"""Write a remote job application for Remote.co listing.

Job: {job['title']} at {job.get('company','the company')}
Description: {job.get('description','')}

Applicant: {your_name} | Skills: {your_skills}
Under 180 words. Reference the role and company. Highlight relevant skills. Clear CTA. Sign as {your_name}.
Output ONLY the message."""
        return call_model(prompt)

    def submit_application(self, job: dict, application_text: str) -> dict:
        return {"submitted": False, "message": f"Apply at {job.get('link')}"}

    def check_replies(self) -> list[dict]:
        return []


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def _extract_skills(text: str) -> list[str]:
    kw = ["Python","JavaScript","TypeScript","React","Node","FastAPI","Django","AWS","Docker","SQL","API","Automation","AI","ML","Go","Rust"]
    return [k for k in kw if k.lower() in text.lower()]
