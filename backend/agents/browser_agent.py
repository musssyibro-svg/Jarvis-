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


# ── Retrying, and the one place it must never happen ─────────────────────────
#
# From mainland China a page load fails constantly and TRANSIENTLY: a DNS
# hiccup, a reset connection, a Cloudflare interstitial that clears on the
# second try. Giving up on the first error makes the freelance engine look
# broken when the network merely blinked.
#
# But retrying is not always safe. Re-trying a SUBMISSION after a timeout can
# put a second proposal in front of a real client under the user's name — the
# request may well have arrived and only the response was lost. So retry is
# opt-in per call site, and bid_executor deliberately does not use it; it
# re-reads the page state instead. See docs/FREELANCER.md.

# Errors worth another attempt: the network, not the page.
_TRANSIENT = (
    "timeout", "timed out", "econnreset", "connection reset", "connection refused",
    "err_network", "err_connection", "err_internet_disconnected", "socket hang up",
    "net::err_", "temporarily unavailable", "502", "503", "504",
    "target closed", "browser has been closed", "page crashed",
)
# Errors where another attempt is pure delay — the answer will not change.
_PERMANENT = (
    "not logged in", "not_logged_in", "404", "no such element", "invalid url",
    "err_name_not_resolved", "err_cert", "access denied", "403",
)


def classify_browser_error(err: str) -> dict:
    """
    {retryable, kind, cause, remedy} for a browser failure.

    Permanent wins over transient when both match: "403 timeout" is a refusal
    with a slow response, and retrying a refusal just makes the user wait.
    """
    e = (err or "").lower()
    if any(p in e for p in _PERMANENT):
        # Both spellings: the executor emits NOT_LOGGED_IN with underscores, so
        # matching only "logged in" filed a login failure as "page not found"
        # and told the user to check the link instead of to log in.
        if ("logged in" in e or "logged_in" in e
                or "403" in e or "access denied" in e):
            return {"retryable": False, "kind": "auth",
                    "cause": "the site refused the request",
                    "remedy": "Log in once by hand via Platform Logins; Jarvis "
                              "reuses that session afterwards."}
        return {"retryable": False, "kind": "not_found",
                "cause": "the page or element isn't there",
                "remedy": "The site's layout may have changed — check the link."}
    if any(t in e for t in _TRANSIENT):
        return {"retryable": True, "kind": "network",
                "cause": "the connection failed part-way",
                "remedy": "Usually the network blinking. Jarvis retries this "
                          "automatically."}
    return {"retryable": False, "kind": "unknown", "cause": err or "unknown failure",
            "remedy": "See the execution log on the Logs screen."}


def with_retry(fn, attempts: int = 3, base_delay: float = 1.5, label: str = ""):
    """
    Run a browser call, retrying only TRANSIENT failures, with backoff.

    NOT for anything that submits. Every attempt is recorded so the log shows
    "succeeded on attempt 2" rather than a silent success that hides a flaky
    site — a site that needs two tries every time is information.
    """
    tried = []
    for attempt in range(1, max(1, attempts) + 1):
        try:
            res = fn()
        except Exception as e:                       # a raise is a failure too
            res = {"success": False, "error": str(e)[:200]}
        if res.get("success"):
            if attempt > 1:
                res["attempts"] = attempt
                res["note"] = f"succeeded on attempt {attempt} of {attempts}"
                _emit_retry(label, f"{label or 'browser'}: worked on attempt {attempt}")
            return res

        info = classify_browser_error(res.get("error", ""))
        tried.append({"attempt": attempt, "error": res.get("error", "")[:120],
                      "kind": info["kind"]})
        if not info["retryable"] or attempt >= attempts:
            res.update(attempts=attempt, tried=tried,
                       cause=info["cause"], what_to_do=info["remedy"],
                       retryable=info["retryable"])
            return res
        delay = base_delay * (2 ** (attempt - 1))    # 1.5s, 3s, 6s
        _emit_retry(label, f"{label or 'browser'} failed ({info['kind']}); "
                           f"retrying in {delay:.0f}s — attempt {attempt + 1} of {attempts}")
        time.sleep(delay)
    return {"success": False, "error": "retries exhausted", "tried": tried}


def _emit_retry(label: str, msg: str) -> None:
    """Say it out loud — a silent retry looks like a hang."""
    try:
        from agents.orchestrator import STATE
        STATE.emit("browser", msg, "warning")
    except Exception:
        pass


# ── Where a URL is allowed to point ──────────────────────────────────────────
#
# This browser is signed in to the user's real accounts. A URL that reaches it
# is a URL acting with those sessions, so the check belongs HERE, at the one
# door every caller goes through, rather than in each caller — the chat path,
# the executor and the income engine would each have to remember, and one of
# them eventually wouldn't.

_ALLOWED_SCHEMES = ("http", "https")

# Loopback. Jarvis's own API is on 127.0.0.1 behind a token the browser doesn't
# have, but the rest of the home network has no such gate, and a router admin
# page reached from a logged-in browser is a real target. Link-local and RFC1918
# are caught by _is_private_host, which says something accurate about each.
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


def check_url(raw: str) -> tuple[str, str]:
    """
    Decide whether a URL may be opened. Returns (url, "") or ("", reason).

    Kept public and separate so the approval gate can ask the same question
    before it prompts, and so the answer is testable without a browser.
    """
    from urllib.parse import urlparse

    url = (raw or "").strip()
    if not url:
        return "", "no URL given"

    # Check the scheme BEFORE prefixing. Prefixing first turns "javascript:x"
    # into "https://javascript:x", which fails for the wrong reason and leaves
    # nothing to tell the user.
    #
    # "localhost:8000" is a host and a port, not a scheme — telling someone
    # that "'localhost:' links are not allowed" would be a true refusal with a
    # false reason, which sends them looking for the wrong problem. A colon
    # followed by digits is a port; anything else is a scheme.
    if ":" in url:
        head, rest = url.split(":", 1)
        looks_like_port = rest.split("/")[0].isdigit()
        if (head and "/" not in head and not looks_like_port
                and head.lower() not in _ALLOWED_SCHEMES):
            return "", f"'{head}:' links are not allowed — only http and https"

    # A second scheme after the first. decompose prefixes bare text with
    # https://, so "file:///C:/…" arrives here as "https://file:///C:/…" —
    # which parses cleanly, has the plausible-looking host "file", and would
    # sail through every check below. Whatever it is, it isn't an address.
    if url.count("://") > 1:
        return "", "that looks like two addresses stuck together, not one"

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception as e:
        return "", f"that isn't a URL I can parse ({e})"

    host = (parsed.hostname or "").lower()
    if not host:
        return "", "that URL has no host"
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        return "", (f"'{host}' is this machine. Jarvis won't drive your "
                    f"logged-in browser at its own control panel.")
    private = _is_private_host(host)
    if private:
        return "", f"'{host}' {private}. Open it yourself if you meant to."
    return url, ""


def _is_private_host(host: str) -> str:
    """
    Why this address is off-limits, or "" if it isn't. Names are left alone.

    Returns the REASON rather than True/False so the refusal can name what the
    address actually is — "on your local network" and "a cloud metadata
    address" send someone to very different places.
    """
    import ipaddress
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return ""           # a hostname; DNS could still resolve inward, but
                            # refusing every name would block the real web
    if ip.is_loopback:
        return "is this machine"
    if ip.is_link_local:
        return "is a link-local address — on some machines that reaches a " \
               "cloud metadata service holding credentials"
    if ip.is_private:
        return "is on your local network, not the internet"
    if ip.is_reserved or ip.is_multicast:
        return "is a reserved address, not a website"
    return ""


# ── The function that was missing ─────────────────────────────────────────────

def navigate(url: str, domain: str = "research", headless: bool = False,
             wait: str = "domcontentloaded") -> dict:
    """
    Open a URL in the managed browser and report what actually loaded.
    Returns {success, url, title, error}. Never raises.
    """
    url, why = check_url(url)
    if why:
        return {"success": False, "error": why, "blocked": True}

    async def _go():
        ctx = await _get_context(headless=headless, domain=domain)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until=wait, timeout=45_000)
        await asyncio.sleep(1.0)
        return {"success": True, "url": page.url, "title": (await page.title())[:120]}

    # Loading a page is idempotent, so it is safe to retry — and from China it
    # needs to be. A single failed goto() used to abandon the whole step.
    res = with_retry(lambda: _run(_go()), attempts=3, label=f"open {url[:40]}")
    if res.get("success"):
        try:
            from services import event_bus
            event_bus.publish("browser.navigated",
                              {"url": res.get("url", url)[:100],
                               "title": res.get("title", "")[:60]})
        except Exception:
            pass
    else:
        res.setdefault("url", url)
    return res


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
