"""platforms/weworkremotely.py — We Work Remotely RSS feeds"""
import re, requests
from bs4 import BeautifulSoup
from platforms.base import BasePlatform

RSS = ["https://weworkremotely.com/remote-jobs.rss",
       "https://weworkremotely.com/categories/remote-programming-jobs.rss"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JarvisBot/3.0)"}

def _clean(t): return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",t)).strip()

class WeWorkRemotelyPlatform(BasePlatform):
    name = "weworkremotely"
    def scan_jobs(self, max_jobs=20):
        jobs, seen = [], set()
        for feed in RSS:
            try:
                soup = BeautifulSoup(requests.get(feed,headers=HEADERS,timeout=15).text, "xml")
                for item in soup.find_all("item"):
                    link = item.find("link")
                    ltext = link.text.strip() if link else ""
                    if ltext in seen: continue
                    seen.add(ltext)
                    title = (item.find("title") or type('',(),{'text':''})()).text.strip()
                    company, job_title = ("", title)
                    if ": " in title: company, job_title = title.split(": ",1)
                    desc = _clean((item.find("description") or type('',(),{'text':''})()).text)[:600]
                    jobs.append({"job_id":f"wwr_{abs(hash(ltext))%999999}","title":job_title,"description":desc,
                                 "skills":[],"company":company,"link":ltext,"date_posted":"","platform":"weworkremotely"})
                    if len(jobs)>=max_jobs: break
            except Exception as e: print(f"[WWR] {e}")
            if len(jobs)>=max_jobs: break
        print(f"[WWR] {len(jobs)} jobs"); return jobs
    def generate_application(self, job, your_name="Ibrahim", your_skills="Python, automation"):
        from services.deepseek_service import call_model
        return call_model(f"Job: {job['title']} at {job.get('company','company')}. Write remote application. Skills: {your_skills}. Under 180 words. Sign as {your_name}.")
    def submit_application(self, job, txt): return {"submitted": False, "message": f"Apply at {job.get('link')}"}
    def check_replies(self): return []
