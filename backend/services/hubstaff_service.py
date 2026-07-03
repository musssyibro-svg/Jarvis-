"""
services/hubstaff_service.py
Hubstaff Talent job discovery via Playwright + HTTP fallback.
Application message generation via DeepSeek-R1.
"""

import asyncio
import sys
import traceback
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EDGE_USER_DATA = str(BASE_DIR / "browser-profile")

HUBSTAFF_JOBS_URL = "https://talent.hubstaff.com/search/jobs"


def _run_in_new_loop(coro):
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Playwright scraper ────────────────────────────────────────────────────────

async def _playwright_hubstaff(max_jobs: int) -> list[dict]:
    from playwright.async_api import async_playwright

    jobs = []
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=EDGE_USER_DATA,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        page = await ctx.new_page()
        try:
            await page.goto(HUBSTAFF_JOBS_URL, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(4)

            card_sels = [
                ".job-listing",
                ".job-card",
                "[class*='job-item']",
                "article.job",
                "li.job",
            ]
            cards = []
            for sel in card_sels:
                cards = await page.query_selector_all(sel)
                if cards:
                    break

            for i, card in enumerate(cards[:max_jobs]):
                try:
                    title_el = await card.query_selector("h2, h3, .job-title, .title, a[href*='/jobs/']")
                    title = (await title_el.inner_text()).strip() if title_el else f"Job #{i+1}"

                    href = await title_el.get_attribute("href") if title_el else ""
                    link = (
                        f"https://talent.hubstaff.com{href}"
                        if href and href.startswith("/")
                        else (href or HUBSTAFF_JOBS_URL)
                    )

                    desc_el = await card.query_selector("p, .description, .summary, .job-desc")
                    desc = (await desc_el.inner_text()).strip() if desc_el else ""

                    company_el = await card.query_selector(".company, .company-name, [class*='company']")
                    company = (await company_el.inner_text()).strip() if company_el else ""

                    skill_els = await card.query_selector_all(".skill, .tag, [class*='skill'], [class*='tag']")
                    skills = []
                    for s in skill_els:
                        t = (await s.inner_text()).strip()
                        if t:
                            skills.append(t)

                    date_el = await card.query_selector(".date, .posted, time, [class*='date']")
                    date_posted = (await date_el.inner_text()).strip() if date_el else ""

                    jobs.append({
                        "job_id":      f"hs_{abs(hash(title + link)) % 999_999}",
                        "title":       title,
                        "description": desc[:600],
                        "skills":      skills,
                        "company":     company,
                        "link":        link,
                        "date_posted": date_posted,
                    })
                except Exception:
                    continue
        except Exception as exc:
            print(f"[HubstaffScraper] Playwright error: {exc}")
            traceback.print_exc()
        finally:
            await ctx.close()
    return jobs


# ── HTTP fallback ─────────────────────────────────────────────────────────────

def _http_hubstaff(max_jobs: int) -> list[dict]:
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            )
        }
        resp = requests.get(HUBSTAFF_JOBS_URL, headers=headers, timeout=20)
        print(f"[HubstaffHTTP] GET {HUBSTAFF_JOBS_URL} -> HTTP {resp.status_code}, "
              f"{len(resp.text)} bytes")
        soup = BeautifulSoup(resp.text, "html.parser")
        # Diagnostic: report how many elements each selector matched so a zero
        # result can be diagnosed (blocked vs DOM changed) without guessing.
        for sel in (".job-listing", ".job-card", "article"):
            print(f"[HubstaffHTTP] selector {sel!r} matched {len(soup.select(sel))} element(s)")
        jobs = []
        for i, card in enumerate(
            soup.select(".job-listing, .job-card, article")[:max_jobs]
        ):
            a = card.select_one("h2 a, h3 a, .title a, a[href*='/jobs/']")
            title = a.get_text(strip=True) if a else f"Job #{i+1}"
            href = a["href"] if a and a.get("href") else ""
            link = f"https://talent.hubstaff.com{href}" if href.startswith("/") else href
            desc = card.select_one("p, .description")
            company_el = card.select_one(".company, .company-name")
            jobs.append({
                "job_id":      f"hs_http_{abs(hash(title)) % 999_999}",
                "title":       title,
                "description": desc.get_text(strip=True)[:600] if desc else "",
                "skills":      [],
                "company":     company_el.get_text(strip=True) if company_el else "",
                "link":        link,
                "date_posted": "",
            })
        print(f"[HubstaffHTTP] Got {len(jobs)} jobs")
        return jobs
    except Exception as exc:
        traceback.print_exc()
        return []


# ── Public entry ──────────────────────────────────────────────────────────────

def scrape_hubstaff_jobs(max_jobs: int = 20) -> list[dict]:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            jobs = ex.submit(_run_in_new_loop, _playwright_hubstaff(max_jobs)).result(timeout=90)
        if jobs:
            return jobs
    except Exception as exc:
        print(f"[HubstaffScraper] Playwright failed: {exc}")
    return _http_hubstaff(max_jobs)


# ── AI application message ────────────────────────────────────────────────────

def generate_application(
    job_title: str,
    job_desc: str,
    company: str,
    your_name: str = "Ibrahim",
    your_skills: str = "Python, automation, web scraping, AI integration, FastAPI",
) -> str:
    from services.deepseek_service import call_model

    prompt = f"""
Write a professional job application message for this Hubstaff Talent listing.

Job Title: {job_title}
Company: {company}
Description: {job_desc}

Applicant: {your_name}
Skills: {your_skills}

Rules:
- Under 180 words
- Open by referencing the specific role and company
- Highlight 1-2 directly relevant skills
- End with a clear call to action
- Sign off as {your_name}
Output ONLY the application message.
""".strip()
    return call_model(prompt)
