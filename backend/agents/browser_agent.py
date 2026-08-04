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
_last_used: dict = {}       # domain -> epoch seconds of last real use (see reap)
_started_at: dict = {}      # domain -> when this browser process was launched
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
    import time as _t
    _last_used[domain] = _t.time()      # lets the janitor tell idle from busy
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
    _started_at[domain] = _t.time()
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


def reap(idle_after_s: float = 1800, max_age_s: float = 6 * 3600) -> dict:
    """
    Housekeeping the maintenance janitor calls on a timer.

    Page reaping used to happen ONLY inside _get_context, i.e. only when
    something asked for the browser. That works while jobs are flowing and does
    nothing the moment they stop: finish a scan at 2am with six pages open, go
    idle until morning, and those six pages — each a live renderer process —
    hold their memory all night on a 16GB machine. Reaping has to be driven by
    the clock, not by traffic.

    A context that has genuinely gone idle is CLOSED OUTRIGHT rather than
    trimmed page by page. Two reasons. Every browser call here runs on a
    throwaway event loop, and Playwright objects belong to the loop that made
    them — so closing individual pages from the janitor's loop is unreliable in
    a way that closing the whole context (already used for shutdown/recovery)
    is not. And closing the context frees strictly more: the browser process
    itself, not just its renderers.

    Nothing is lost by doing this. The profile lives on disk, so logins survive
    a context close and the next navigate relaunches straight back into the
    logged-in session. That's the distinction the original leak fix got right
    and this keeps: recycle the RUNNING BROWSER, never the profile.

    Idle time alone is not enough protection for a 24-hour run. With the income
    engine scanning every 20 minutes, a context is touched often enough that it
    is never "idle" — and then a single Chromium process accumulates for a full
    day, which is exactly the leak the long-run audits worried about. So there
    is also a hard age cap: however busy it has been, a browser that has been
    running for `max_age_s` gets recycled at the next quiet moment. Cheap
    insurance — relaunching costs a couple of seconds and the profile makes it
    invisible.

    Contexts still in active use are left alone entirely — the maintenance
    janitor won't even call this while the browser lock is held.
    """
    import time as _t
    result = {"checked": 0, "closed_idle": [], "recycled_old": [],
              "dropped_contexts": []}
    now = _t.time()

    for domain, ctx in list(_ctx.items()):
        result["checked"] += 1
        try:
            _ = list(ctx.pages)         # cheap liveness probe
        except Exception:
            # The context object is unusable — the browser died (crash, or the
            # user closed the window). Drop the handle so the next call
            # relaunches cleanly instead of throwing.
            _ctx.pop(domain, None)
            _last_used.pop(domain, None)
            _started_at.pop(domain, None)
            result["dropped_contexts"].append(domain)
            continue

        idle = now - _last_used.get(domain, now)
        age = now - _started_at.get(domain, now)
        if idle > idle_after_s:
            if close_domain(domain).get("ok"):
                result["closed_idle"].append(domain)
        elif age > max_age_s:
            if close_domain(domain).get("ok"):
                result["recycled_old"].append(
                    {"domain": domain, "age_h": round(age / 3600, 1)})

    if any(result[k] for k in ("closed_idle", "recycled_old", "dropped_contexts")):
        try:
            from services import event_bus
            event_bus.publish("browser.reaped", result)
        except Exception:
            pass
    return result


def close_domain(domain: str = "freelance") -> dict:
    """Close one domain's browser (used on shutdown / recovery), keeping others."""
    ctx = _ctx.pop(domain, None)
    _last_used.pop(domain, None)
    _started_at.pop(domain, None)
    if not ctx:
        return {"ok": True, "note": "not open"}
    try:
        _run(ctx.close(), timeout=20)
    except Exception:
        pass
    return {"ok": True, "closed": domain}


def status() -> dict:
    import time as _t
    now = _t.time()
    out = {}
    for domain, ctx in list(_ctx.items()):
        idle = round(now - _last_used.get(domain, now))
        age = round(now - _started_at.get(domain, now))
        try:
            out[domain] = {"open": True, "pages": len(ctx.pages),
                           "idle_s": idle, "age_s": age}
        except Exception:
            out[domain] = {"open": False, "pages": 0, "idle_s": idle, "age_s": age}
    for d in PROFILES:
        out.setdefault(d, {"open": False, "pages": 0, "idle_s": None, "age_s": None})
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
