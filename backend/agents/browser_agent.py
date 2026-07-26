"""
agents/browser_agent.py — persistent browser sessions, login-once, reuse forever.

Two things were wrong and are fixed here:

1. `navigate()` DID NOT EXIST. executor_agent imported it, the import failed, and
   every browse action returned "browser navigation not implemented (Phase 5)".
   Browsing simply did not work. It does now.

2. The single global context leaked: pages were opened and never counted or
   closed, so a 24/7 run bloated Chromium until submissions failed.

On the leak, we deliberately DO NOT do what one audit suggested (destroy the
whole context every 30 minutes). That profile holds your Freelancer/QQ/Doubao
logins and browser fingerprint — throwing it away every half hour means constant
re-logins and more bot challenges. Instead:

    * pages are tracked and closed (the actual leak),
    * idle pages are reaped above a cap,
    * the persistent PROFILE is never destroyed on a timer.

Profiles are also split per domain (freelance / research / desktop), so a crash
or a Cloudflare block on one doesn't take the others down with it.
"""
import asyncio
import os
import sys
import threading
import time
from pathlib import Path

from agents.base_agent import BaseAgent

BASE_DIR = Path(__file__).resolve().parent.parent

# One profile per domain: an incident in one is contained.
PROFILES = {
    "freelance": str(BASE_DIR / "browser-profile"),      # keep the existing path
    "research":  str(BASE_DIR / "browser-profile-research"),
    "desktop":   str(BASE_DIR / "browser-profile-desktop"),
}
PROFILE_DIR = PROFILES["freelance"]     # back-compat for existing imports

for _p in PROFILES.values():
    os.makedirs(_p, exist_ok=True)

MAX_OPEN_PAGES = 6          # reap idle pages beyond this — the real leak
_ctx: dict = {}             # domain -> context
_ctx_lock = threading.Lock()


def _new_loop():
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()


async def _get_context(headless: bool = True, domain: str = "freelance"):
    """
    Get (or create) the persistent context for a domain. Reaps surplus pages so
    memory stays bounded WITHOUT discarding the logged-in profile.
    """
    ctx = _ctx.get(domain)
    if ctx:
        try:
            pages = list(ctx.pages)
            # Close the oldest idle pages if we're above the cap. This is the
            # actual source of the leak; the profile itself is fine to keep.
            if len(pages) > MAX_OPEN_PAGES:
                for p in pages[:-MAX_OPEN_PAGES]:
                    try:
                        await p.close()
                    except Exception:
                        pass
            return ctx
        except Exception:
            # context died (browser closed/crashed) — drop it and relaunch
            _ctx.pop(domain, None)

    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        user_data_dir=PROFILES.get(domain, PROFILE_DIR),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled",
              "--no-sandbox", "--disable-dev-shm-usage"],
    )
    _ctx[domain] = ctx
    return ctx


def _run(coro, timeout: float = 90):
    """Run an async browser coroutine from sync code (Windows-safe)."""
    import concurrent.futures
    loop = _new_loop()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(loop.run_until_complete, coro).result(timeout=timeout)
    finally:
        try:
            loop.close()
        except Exception:
            pass


# ── The function that was missing ─────────────────────────────────────────────

def navigate(url: str, domain: str = "research", headless: bool = False,
             wait: str = "domcontentloaded") -> dict:
    """
    Open a URL in the managed browser and report what actually loaded.
    Returns {success, url, title, error}. Never raises.
    """
    if not url:
        return {"success": False, "error": "no URL given"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    async def _go():
        ctx = await _get_context(headless=headless, domain=domain)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until=wait, timeout=45_000)
        await asyncio.sleep(1.0)
        return {"success": True, "url": page.url, "title": (await page.title())[:120]}

    try:
        res = _run(_go())
        try:
            from services import event_bus
            event_bus.publish("browser.navigated",
                              {"url": res.get("url", url)[:100],
                               "title": res.get("title", "")[:60]})
        except Exception:
            pass
        return res
    except Exception as e:
        return {"success": False, "url": url, "error": str(e)[:200]}


def current_page_text(domain: str = "research", limit: int = 4000) -> dict:
    """Readable text of the current page — lets Jarvis actually use the web."""
    async def _read():
        ctx = await _get_context(headless=False, domain=domain)
        if not ctx.pages:
            return {"success": False, "error": "no page open"}
        page = ctx.pages[0]
        txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return {"success": True, "url": page.url,
                "title": (await page.title())[:120], "text": (txt or "")[:limit]}
    try:
        return _run(_read())
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def close_domain(domain: str = "freelance") -> dict:
    """Close one domain's browser (used on shutdown / recovery), keeping others."""
    ctx = _ctx.pop(domain, None)
    if not ctx:
        return {"ok": True, "note": "not open"}
    try:
        _run(ctx.close(), timeout=20)
    except Exception:
        pass
    return {"ok": True, "closed": domain}


def status() -> dict:
    out = {}
    for domain, ctx in list(_ctx.items()):
        try:
            out[domain] = {"open": True, "pages": len(ctx.pages)}
        except Exception:
            out[domain] = {"open": False, "pages": 0}
    for d in PROFILES:
        out.setdefault(d, {"open": False, "pages": 0})
    return {"contexts": out, "max_pages_per_context": MAX_OPEN_PAGES}


class BrowserAgent(BaseAgent):
    name = "browser"

    def run(self, context: dict) -> dict:
        action   = context.get("action", "check_login")
        headless = context.get("headless", True)
        domain   = context.get("domain", "freelance")
        feed     = []

        if action == "navigate" or action == "open_url":
            r = navigate(context.get("url", ""), domain=domain, headless=headless)
            feed.append(self.log(f"Navigate: {r.get('title') or r.get('error')}"))
            return {"result": r, "feed": feed}

        if action == "read_page":
            r = current_page_text(domain=domain)
            return {"result": r, "feed": feed}

        if action == "check_login":
            r = navigate(context.get("url", "https://www.google.com"),
                         domain=domain, headless=headless)
            status_str = f"ok:{r.get('title','')[:40]}" if r.get("success") else f"error:{r.get('error')}"
            feed.append(self.log(f"Login check: {status_str}"))
            return {"result": status_str, "feed": feed}

        return {"result": "unknown action", "feed": feed}
