"""
agents/browser_agent.py
BrowserAgent — persistent browser session, login-once, session reuse.
Handles submission workflows via Playwright.
"""
import asyncio
import os
import sys
from pathlib import Path
from agents.base_agent import BaseAgent

BASE_DIR        = Path(__file__).resolve().parent.parent
PROFILE_DIR     = str(BASE_DIR / "browser-profile")
os.makedirs(PROFILE_DIR, exist_ok=True)

_ctx = None  # persistent browser context (reused across calls)


def _new_loop():
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()


async def _get_context(headless: bool = True):
    global _ctx
    if _ctx:
        try:
            await _ctx.new_page()  # test if still alive
            return _ctx
        except Exception:
            _ctx = None

    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    _ctx = await p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    return _ctx


class BrowserAgent(BaseAgent):
    name = "browser"

    def run(self, context: dict) -> dict:
        action   = context.get("action", "check_login")
        headless = context.get("headless", True)
        feed     = []

        if action == "check_login":
            result = self._check_login(context.get("url", "https://www.google.com"), headless)
            feed.append(self.log(f"Login check: {result}"))
            return {"result": result, "feed": feed}

        if action == "open_url":
            url = context.get("url", "")
            self._open_url(url, headless)
            feed.append(self.log(f"Opened: {url}"))
            return {"result": "opened", "feed": feed}

        return {"result": "unknown action", "feed": feed}

    def _check_login(self, url: str, headless: bool) -> str:
        import concurrent.futures
        async def _do():
            ctx = await _get_context(headless)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                title = await page.title()
                return f"ok:{title[:40]}"
            finally:
                await page.close()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                loop = _new_loop()
                return ex.submit(loop.run_until_complete, _do()).result(timeout=45)
        except Exception as e:
            return f"error:{e}"

    def _open_url(self, url: str, headless: bool):
        import webbrowser
        webbrowser.open(url)
