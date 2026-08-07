"""platforms/remoteok.py — RemoteOK public JSON API"""
import re

import requests

from platforms.base import BasePlatform

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JarvisBot/3.0)", "Accept": "application/json"}

class RemoteOKPlatform(BasePlatform):
    name = "remoteok"
    def scan_jobs(self, max_jobs=20):
        try:
            resp = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=20)
            resp.raise_for_status()
            raw = [i for i in resp.json() if isinstance(i, dict) and i.get("id")]
            jobs = []
            for item in raw[:max_jobs]:
                tags = item.get("tags") or []
                jobs.append({
                    "job_id": f"rok_{item.get('id','')}",
                    "title": item.get("position") or item.get("title") or "Remote Job",
                    "description": re.sub(r"<[^>]+>", " ", item.get("description") or "")[:600],
                    "skills": tags if isinstance(tags, list) else [],
                    "company": item.get("company") or "",
                    "link": item.get("url") or f"https://remoteok.com/remote-jobs/{item.get('id','')}",
                    "date_posted": str(item.get("date",""))[:10],
                    "platform": "remoteok",
                })
            print(f"[RemoteOK] {len(jobs)} jobs")
            return jobs
        except Exception as e:
            print(f"[RemoteOK] {e}"); return []
    def generate_application(self, job, your_name="Ibrahim", your_skills="Python, automation, web scraping, AI, FastAPI"):
        from services.deepseek_service import call_model
        return call_model(f"Write a remote job application for {job['title']} at {job.get('company','the company')}. Skills: {your_skills}. Under 160 words. Sign as {your_name}. Output ONLY the message.")
    def submit_application(self, job, txt): return {"submitted": False, "message": f"Apply at {job.get('link')}"}
    def check_replies(self): return []
