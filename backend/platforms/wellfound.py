"""
platforms/wellfound.py
Wellfound (AngelList Talent) — scrapes public job listings.
Note: Heavy JS site. Falls back to their public sitemap + individual pages.
"""

import re
import traceback

import requests
from bs4 import BeautifulSoup

from platforms.base import BasePlatform

BASE     = "https://wellfound.com"
JOBS_URL = "https://wellfound.com/jobs"
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class WellfoundPlatform(BasePlatform):
    name = "wellfound"

    def scan_jobs(self, max_jobs: int = 20) -> list[dict]:
        jobs = self._try_html(max_jobs)
        if not jobs:
            jobs = self._try_sitemap(max_jobs)
        print(f"[Wellfound] Got {len(jobs)} jobs")
        return jobs

    def _try_html(self, max_jobs: int) -> list[dict]:
        try:
            resp = requests.get(JOBS_URL, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("[class*='JobListing'], [class*='job-listing'], [class*='JobCard'], article")
            jobs = []
            for i, card in enumerate(cards[:max_jobs]):
                a = card.select_one("a[href*='/jobs/']")
                title_el = card.select_one("h2, h3, [class*='title'], [class*='role']")
                title = title_el.get_text(strip=True) if title_el else (a.get_text(strip=True) if a else f"Job #{i+1}")
                href = a["href"] if a and a.get("href") else ""
                link = f"{BASE}{href}" if href.startswith("/") else href
                co_el = card.select_one("[class*='company'], [class*='startup']")
                company = co_el.get_text(strip=True) if co_el else ""
                desc_el = card.select_one("p, [class*='description'], [class*='summary']")
                desc = desc_el.get_text(strip=True)[:600] if desc_el else ""
                skill_els = card.select("[class*='skill'], [class*='tag'], [class*='label']")
                skills = [s.get_text(strip=True) for s in skill_els if s.get_text(strip=True)]
                jobs.append({
                    "job_id":      f"wf_{abs(hash(link)) % 999_999}",
                    "title":       title,
                    "description": desc,
                    "skills":      skills[:10],
                    "company":     company,
                    "link":        link,
                    "date_posted": "",
                    "platform":    "wellfound",
                })
            return jobs
        except Exception:
            traceback.print_exc()
            return []

    def _try_sitemap(self, max_jobs: int) -> list[dict]:
        try:
            r = requests.get(f"{BASE}/sitemap.xml", headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "xml")
            urls = [loc.text for loc in soup.find_all("loc") if "/jobs/" in loc.text][:max_jobs]
            jobs = []
            for url in urls:
                try:
                    pr = requests.get(url, headers=HEADERS, timeout=10)
                    ps = BeautifulSoup(pr.text, "html.parser")
                    title_el = ps.select_one("h1")
                    title = title_el.get_text(strip=True) if title_el else url.split("/")[-1].replace("-"," ").title()
                    co_el = ps.select_one("[class*='company'], [class*='startup']")
                    company = co_el.get_text(strip=True) if co_el else ""
                    desc_el = ps.select_one("[class*='description'], main p")
                    desc = desc_el.get_text(strip=True)[:600] if desc_el else ""
                    jobs.append({
                        "job_id":      f"wf_sm_{abs(hash(url)) % 999_999}",
                        "title":       title, "description": desc,
                        "skills":      [], "company": company,
                        "link":        url, "date_posted": "", "platform": "wellfound",
                    })
                except Exception:
                    continue
            return jobs
        except Exception:
            return []

    def generate_application(self, job: dict, your_name: str = "Ibrahim",
                              your_skills: str = "Python, automation, web scraping, AI integration, FastAPI") -> str:
        from services.deepseek_service import call_model
        prompt = f"""Write a startup job application for a Wellfound listing.

Job: {job['title']} at {job.get('company','the startup')}
Description: {job.get('description','')}

Applicant: {your_name} | Skills: {your_skills}
Under 180 words. Show startup enthusiasm. Reference the company mission if possible.
Highlight most relevant skill. Clear CTA. Sign as {your_name}.
Output ONLY the message."""
        return call_model(prompt)

    def submit_application(self, job: dict, application_text: str) -> dict:
        return {"submitted": False, "message": f"Apply at {job.get('link')}"}

    def check_replies(self) -> list[dict]:
        return []
