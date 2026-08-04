"""
platforms/hubstaff.py  —  Fixed Hubstaff Talent scraper
ROOT CAUSE: talent.hubstaff.com loads jobs via XHR after page paint.
Pure Playwright headless + wrong selectors = 0 results.

Fix strategy (3 layers):
  1. Direct JSON API endpoint (discovered via network tab)
  2. RSS/sitemap walk (always has real URLs)
  3. Requests + BS4 on individual job pages
"""

import re
import requests
from bs4 import BeautifulSoup
from platforms.base import BasePlatform

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

class HubstaffPlatform(BasePlatform):
    name = "hubstaff"

    def scan_jobs(self, max_jobs: int = 20) -> list[dict]:
        jobs = []
        # Layer 1: try known API endpoints
        for url in [
            "https://talent.hubstaff.com/api/v2/jobs?page=1&per_page=20",
            "https://talent.hubstaff.com/api/jobs?page=1&per_page=20",
        ]:
            jobs = self._try_api(url, max_jobs)
            if jobs:
                print(f"[Hubstaff] API layer got {len(jobs)} jobs")
                return jobs

        # Layer 2: sitemap walk (guaranteed real job URLs)
        jobs = self._try_sitemap(max_jobs)
        if jobs:
            print(f"[Hubstaff] Sitemap layer got {len(jobs)} jobs")
            return jobs

        # Layer 3: search page with session cookies
        jobs = self._try_search_page(max_jobs)
        print(f"[Hubstaff] Search-page layer got {len(jobs)} jobs")
        return jobs

    def _try_api(self, url: str, max_jobs: int) -> list[dict]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return []
            ct = r.headers.get("content-type", "")
            if "json" not in ct:
                return []
            data = r.json()
            raw = data if isinstance(data, list) else \
                  data.get("jobs", data.get("data", data.get("results", [])))
            if not isinstance(raw, list) or not raw:
                return []
            return [self._normalise(item, i) for i, item in enumerate(raw[:max_jobs])]
        except Exception as e:
            print(f"[Hubstaff._try_api] {e}")
            return []

    def _try_sitemap(self, max_jobs: int) -> list[dict]:
        try:
            sitemaps = [
                "https://talent.hubstaff.com/sitemap.xml",
                "https://talent.hubstaff.com/sitemaps/jobs.xml",
            ]
            job_urls = []
            for sm_url in sitemaps:
                r = requests.get(sm_url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(r.text, "xml")
                job_urls += [
                    loc.text.strip() for loc in soup.find_all("loc")
                    if re.search(r"/jobs?/[^/]+$", loc.text)
                ]
                if job_urls:
                    break

            jobs = []
            for url in job_urls[:max_jobs]:
                try:
                    pr = requests.get(url, headers=HEADERS, timeout=10)
                    ps = BeautifulSoup(pr.text, "html.parser")
                    title = (ps.select_one("h1") or ps.select_one("title") or ps.new_tag("x"))
                    title_text = title.get_text(strip=True).replace(" | Hubstaff Talent", "")
                    desc_el = ps.select_one(".job-description, #job-description, [class*='description'], main article")
                    desc = _clean(desc_el.get_text(" "))[:600] if desc_el else ""
                    co_el = ps.select_one("[class*='company'], [class*='employer']")
                    company = co_el.get_text(strip=True) if co_el else ""
                    jobs.append({
                        "job_id": f"hs_sm_{abs(hash(url)) % 999999}",
                        "title": title_text or url.split("/")[-1].replace("-", " ").title(),
                        "description": desc, "skills": _extract_skills(desc),
                        "company": company, "link": url,
                        "date_posted": "", "platform": "hubstaff",
                    })
                except Exception:
                    continue
            return jobs
        except Exception as e:
            print(f"[Hubstaff._try_sitemap] {e}")
            return []

    def _try_search_page(self, max_jobs: int) -> list[dict]:
        try:
            session = requests.Session()
            session.headers.update(HEADERS)
            # Seed cookies
            session.get("https://talent.hubstaff.com/search/jobs", timeout=15)
            # Try XHR JSON
            for xhr in [
                "https://talent.hubstaff.com/search/jobs.json?page=1",
                "https://talent.hubstaff.com/api/search/jobs?page=1",
            ]:
                r = session.get(xhr, headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"}, timeout=10)
                if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                    data = r.json()
                    raw = data if isinstance(data, list) else data.get("jobs", data.get("results", []))
                    if raw:
                        return [self._normalise(x, i) for i, x in enumerate(raw[:max_jobs])]

            # HTML parse as last resort
            r = session.get("https://talent.hubstaff.com/search/jobs", timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("[class*='JobCard'], [class*='job-card'], [class*='job_card'], .job-listing, li[data-job]")
            jobs = []
            for i, card in enumerate(cards[:max_jobs]):
                a = card.select_one("a[href]")
                href = a["href"] if a else ""
                link = f"https://talent.hubstaff.com{href}" if href.startswith("/") else href
                title_el = card.select_one("h2, h3, [class*='title']")
                title = title_el.get_text(strip=True) if title_el else f"Job #{i+1}"
                desc_el = card.select_one("p, [class*='desc'], [class*='summary']")
                desc = desc_el.get_text(strip=True)[:600] if desc_el else ""
                co_el = card.select_one("[class*='company'], [class*='employer']")
                company = co_el.get_text(strip=True) if co_el else ""
                jobs.append({
                    "job_id": f"hs_html_{abs(hash(link or title)) % 999999}",
                    "title": title, "description": desc,
                    "skills": _extract_skills(desc), "company": company,
                    "link": link, "date_posted": "", "platform": "hubstaff",
                })
            return jobs
        except Exception as e:
            print(f"[Hubstaff._try_search_page] {e}")
            return []

    def _normalise(self, item: dict, i: int) -> dict:
        title = item.get("title") or item.get("name") or f"Job #{i+1}"
        desc  = _clean(str(item.get("description") or item.get("summary") or ""))[:600]
        co    = item.get("company") or {}
        company = co.get("name", "") if isinstance(co, dict) else str(co)
        skills = [s.get("name", s) if isinstance(s, dict) else str(s)
                  for s in item.get("skills", item.get("tags", []))]
        slug  = item.get("slug") or item.get("id") or i
        link  = item.get("url") or f"https://talent.hubstaff.com/jobs/{slug}"
        return {
            "job_id":      f"hs_{item.get('id', abs(hash(title)) % 999999)}",
            "title":       title,
            "description": desc,
            "skills":      skills,
            "company":     company,
            "link":        link,
            "date_posted": str(item.get("created_at", ""))[:10],
            "platform":    "hubstaff",
        }

    def generate_application(self, job: dict, your_name="Ibrahim",
                              your_skills="Python, automation, web scraping, AI integration, FastAPI") -> str:
        from services.deepseek_service import call_model
        return call_model(f"""Write a professional Hubstaff Talent job application.
Job: {job['title']} | Company: {job.get('company','the company')}
Description: {job.get('description','')}
Applicant: {your_name} | Skills: {your_skills}
Under 180 words. Reference role and company. Highlight 1-2 relevant skills. Clear CTA. Sign as {your_name}.
Output ONLY the application message.""")

    def submit_application(self, job, application_text):
        return {"submitted": False, "message": f"Copy text and apply at: {job.get('link')}"}

    def check_replies(self):
        return []


def _clean(t): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()
def _extract_skills(t):
    kw = ["Python","JavaScript","TypeScript","React","Node","FastAPI","Django","AWS","Docker","SQL","PostgreSQL","Redis","API","Automation","AI","ML","Go","Rust","PHP","Ruby"]
    return [k for k in kw if k.lower() in t.lower()]
