"""
services/freelancer_api.py
Freelancer.com integration.
Priority: Official API  →  Browser scrape fallback  →  HTTP fallback
"""

import asyncio
import concurrent.futures
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

FL_TOKEN = os.getenv("FREELANCER_OAUTH_TOKEN", "")
EDGE_USER_DATA = str(BASE_DIR / "browser-profile")


# ── Official API ─────────────────────────────────────────────────────────────

def fetch_api_jobs(max_jobs: int = 20, query: str = "python automation scraping") -> list:
    """
    Use Freelancer REST API if token is configured.
    Returns list of job dicts or empty list on failure.
    """
    if not FL_TOKEN:
        return []
    try:
        import requests

        url = "https://www.freelancer.com/api/projects/0.1/projects/active/"
        headers = {"Freelancer-OAuth-V1": FL_TOKEN}
        params = {
            "query": query,
            "job_details": "true",
            "full_description": "true",
            "limit": max_jobs,
        }
        r = requests.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        projects = data.get("result", {}).get("projects", [])
        jobs = []
        for i, p in enumerate(projects):
            budget = p.get("budget", {})
            budget_str = (
                f"${budget.get('minimum', 0)}-${budget.get('maximum', 0)}"
                if budget else "Not specified"
            )
            jobs.append(
                {
                    "id": f"fl_api_{p.get('id', i)}",
                    "platform": "freelancer",
                    "title": p.get("title", f"Job #{i}"),
                    "description": (p.get("description") or "")[:500],
                    "budget": budget_str,
                    "skills": [j.get("name", "") for j in p.get("jobs", [])],
                    "link": f"https://www.freelancer.com/projects/{p.get('seo_url', '')}",
                    "score": 0,
                }
            )
        print(f"[Freelancer API] Got {len(jobs)} jobs")
        return jobs
    except Exception as exc:
        print(f"[Freelancer API] Failed: {exc}")
        return []


# ── Playwright scraper ────────────────────────────────────────────────────────

def _run_in_new_loop(coro):
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _playwright_freelancer(max_jobs: int) -> list:
    from playwright.async_api import async_playwright

    jobs = []
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=EDGE_USER_DATA,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        page = await ctx.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        await page.goto(
            "https://www.freelancer.com/jobs/?languages=en",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await asyncio.sleep(3)

        SELECTORS = [
            ".JobSearchCard-item",
            "[data-testid='job-item']",
            ".project-list-item",
        ]
        elements = []
        for sel in SELECTORS:
            elements = await page.query_selector_all(sel)
            if elements:
                break

        for i, el in enumerate(elements[:max_jobs]):
            try:
                title_el = await el.query_selector(
                    ".JobSearchCard-primary-heading a, h2 a, a[href*='/projects/']"
                )
                title = (await title_el.inner_text()).strip() if title_el else f"Job #{i}"
                href = await title_el.get_attribute("href") if title_el else ""
                link = (
                    f"https://www.freelancer.com{href}"
                    if href and href.startswith("/")
                    else (href or "")
                )
                desc_el = await el.query_selector(".JobSearchCard-primary-description, p")
                desc = (await desc_el.inner_text()).strip() if desc_el else ""
                budget_el = await el.query_selector(".JobSearchCard-primary-price, .budget")
                budget = (await budget_el.inner_text()).strip() if budget_el else "Not specified"
                skill_els = await el.query_selector_all(".JobSearchCard-primary-tags a, .tags a")
                skills = [(await s.inner_text()).strip() for s in skill_els]

                jobs.append(
                    {
                        "id": f"fl_{i}_{abs(hash(title)) % 99_999}",
                        "platform": "freelancer",
                        "title": title,
                        "description": desc[:500],
                        "budget": budget,
                        "skills": skills,
                        "link": link,
                        "score": 0,
                    }
                )
            except Exception:
                continue
        await ctx.close()
    return jobs


def _http_fallback(max_jobs: int) -> list:
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            )
        }
        resp = requests.get(
            "https://www.freelancer.com/jobs/?languages=en", headers=headers, timeout=20
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        jobs = []
        for i, card in enumerate(
            soup.select(".JobSearchCard-item, .project-list-item")[:max_jobs]
        ):
            a = card.select_one("h2 a, .JobSearchCard-primary-heading a")
            title = a.get_text(strip=True) if a else f"Job #{i}"
            href = a["href"] if a and a.get("href") else ""
            link = f"https://www.freelancer.com{href}" if href.startswith("/") else href
            desc = card.select_one(".JobSearchCard-primary-description, p")
            budget_el = card.select_one(".JobSearchCard-primary-price")
            jobs.append(
                {
                    "id": f"fl_http_{i}_{abs(hash(title)) % 99_999}",
                    "platform": "freelancer",
                    "title": title,
                    "description": desc.get_text(strip=True)[:500] if desc else "",
                    "budget": budget_el.get_text(strip=True) if budget_el else "Not specified",
                    "skills": [],
                    "link": link,
                    "score": 0,
                }
            )
        print(f"[Freelancer HTTP] Got {len(jobs)} jobs")
        return jobs
    except Exception:
        traceback.print_exc()
        return []


def scrape_freelancer(max_jobs: int = 20) -> list:
    """Try API → Playwright → HTTP fallback."""
    jobs = fetch_api_jobs(max_jobs)
    if jobs:
        return jobs
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run_in_new_loop, _playwright_freelancer(max_jobs))
            jobs = future.result(timeout=90)
        if jobs:
            return jobs
    except Exception as exc:
        print(f"[Playwright] Failed: {exc}")
    return _http_fallback(max_jobs)
