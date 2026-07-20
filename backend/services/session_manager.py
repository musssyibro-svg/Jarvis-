"""
services/session_manager.py — Per-platform login sessions (login once, reuse forever).

The missing piece between "Jarvis found a job" and "Jarvis submitted the bid":
knowing whether the persistent browser profile is actually logged in to each
freelance platform, and giving the user a one-click way to log in when not.

How it works:
  * All Playwright work shares ONE persistent profile dir (backend/browser-profile)
    — the same one bid_executor and browser_monitor use — so a login done here
    is immediately reusable by bid submission and inbox monitoring.
  * status(): headless visit to each platform's account page; a redirect to a
    login/sign-in URL (or a visible password field) means "logged out".
  * open_login(platform): opens a VISIBLE browser window on the login page and
    keeps it open until the user closes it. If the vault has credentials for
    the platform, the form is pre-filled (never auto-submitted — the user
    presses the button, which also handles captchas/2FA naturally).

Results are cached (LOGIN_CACHE_TTL) because each check is a real page load.
"""
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR    = Path(__file__).resolve().parent.parent
PROFILE_DIR = str(BASE_DIR / "browser-profile")

LOGIN_CACHE_TTL = 300  # seconds

# Heuristics per platform. `check_url` should require auth; landing on a URL
# containing one of LOGIN_MARKERS (or seeing a password input) = logged out.
PLATFORMS = {
    "freelancer": {
        "label":     "Freelancer.com",
        "login_url": "https://www.freelancer.com/login",
        "check_url": "https://www.freelancer.com/dashboard",
    },
    "upwork": {
        "label":     "Upwork",
        "login_url": "https://www.upwork.com/ab/account-security/login",
        "check_url": "https://www.upwork.com/nx/find-work/",
    },
    "fiverr": {
        "label":     "Fiverr",
        "login_url": "https://www.fiverr.com/login",
        "check_url": "https://www.fiverr.com/users/settings",
    },
    "peopleperhour": {
        "label":     "PeoplePerHour",
        "login_url": "https://www.peopleperhour.com/site/login",
        "check_url": "https://www.peopleperhour.com/dashboard",
    },
    "hubstaff": {
        "label":     "Hubstaff Talent",
        "login_url": "https://talent.hubstaff.com/users/sign_in",
        "check_url": "https://talent.hubstaff.com/profile",
    },
    "contra": {
        "label":     "Contra",
        "login_url": "https://contra.com/login",
        "check_url": "https://contra.com/inbox",
    },
    "wellfound": {
        "label":     "Wellfound",
        "login_url": "https://wellfound.com/login",
        "check_url": "https://wellfound.com/jobs",
    },
}

LOGIN_MARKERS = ("login", "sign_in", "signin", "sign-in", "account-security", "authenticate")

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_login_windows: dict[str, bool] = {}   # platform -> a headed window is open


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_platforms() -> list[dict]:
    return [{"id": pid, **{k: v for k, v in meta.items() if k != "check_url"}}
            for pid, meta in PLATFORMS.items()]


# ── Status checks ─────────────────────────────────────────────────────────────

def _check_one_sync(page, platform: str) -> dict:
    meta = PLATFORMS[platform]
    entry = {"platform": platform, "label": meta["label"], "checked_at": _now()}
    try:
        page.goto(meta["check_url"], wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2500)
        url = (page.url or "").lower()
        if any(m in url for m in LOGIN_MARKERS):
            entry.update(logged_in=False, reason="redirected to login page")
            return entry
        try:
            pw_field = page.query_selector("input[type='password']")
        except Exception:
            pw_field = None
        if pw_field:
            entry.update(logged_in=False, reason="login form visible")
            return entry
        entry.update(logged_in=True, reason="session active")
    except Exception as e:
        entry.update(logged_in=None, reason=f"check failed: {str(e)[:120]}")
    return entry


def check_status(platforms: list[str] | None = None, refresh: bool = False) -> dict:
    """
    Login status for each platform, from cache unless refresh/expired.
    Runs the real checks in one shared headless persistent context, guarded by
    the single-owner browser lock so it never races bid submission.
    """
    wanted = [p for p in (platforms or list(PLATFORMS)) if p in PLATFORMS]
    now = time.time()
    with _cache_lock:
        stale = [p for p in wanted
                 if refresh or p not in _cache
                 or now - _cache[p].get("_ts", 0) > LOGIN_CACHE_TTL]

    if stale:
        from core.browser_lock import acquire, release
        lock = acquire("session_manager")
        if not lock.get("ok"):
            # Browser busy (probably submitting a bid) — serve cache + note.
            with _cache_lock:
                results = [_cache.get(p, {"platform": p, "logged_in": None,
                                          "label": PLATFORMS[p]["label"],
                                          "reason": "browser busy — try again"})
                           for p in wanted]
            return {"platforms": _strip(results), "busy": True}
        try:
            _run_checks(stale)
        finally:
            release("session_manager")

    with _cache_lock:
        results = [_cache.get(p, {"platform": p, "logged_in": None,
                                  "label": PLATFORMS[p]["label"],
                                  "reason": "not checked yet"}) for p in wanted]
    return {"platforms": _strip(results), "busy": False}


def _run_checks(platforms: list[str]) -> None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR, headless=True,
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox", "--disable-dev-shm-usage"])
            page = ctx.new_page()
            for platform in platforms:
                entry = _check_one_sync(page, platform)
                entry["_ts"] = time.time()
                with _cache_lock:
                    _cache[platform] = entry
            ctx.close()
    except Exception as e:
        err = f"playwright unavailable: {str(e)[:120]}"
        with _cache_lock:
            for platform in platforms:
                _cache[platform] = {"platform": platform,
                                    "label": PLATFORMS[platform]["label"],
                                    "logged_in": None, "reason": err,
                                    "checked_at": _now(), "_ts": time.time()}


def _strip(entries: list[dict]) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "_ts"} for e in entries]


# ── Interactive login window ──────────────────────────────────────────────────

USERNAME_SELECTORS = [
    "input[type='email']", "input[name='email']", "input[name='username']",
    "input[name='user']", "input[id*='email' i]", "input[id*='username' i]",
    "input[autocomplete='username']",
]
PASSWORD_SELECTORS = ["input[type='password']"]


def open_login(platform: str) -> dict:
    """
    Open a VISIBLE browser on the platform's login page using the shared
    persistent profile. Pre-fills the form from the vault when credentials
    exist. The window stays open until the user closes it; the session cookie
    lands in the shared profile so every other Jarvis feature can reuse it.
    """
    platform = (platform or "").strip().lower()
    if platform not in PLATFORMS:
        return {"ok": False, "error": f"unknown platform '{platform}'",
                "known": list(PLATFORMS)}
    if _login_windows.get(platform):
        return {"ok": True, "already_open": True,
                "message": f"A login window for {PLATFORMS[platform]['label']} is already open."}

    from core.browser_lock import acquire
    lock = acquire(f"login:{platform}")
    if not lock.get("ok"):
        return {"ok": False, "error": lock.get("message", "Browser busy"),
                "busy_with": lock.get("busy_with")}

    t = threading.Thread(target=_login_window_worker, args=(platform,), daemon=True)
    t.start()
    cred = None
    try:
        from services.vault import get_credential
        cred = get_credential(platform)
    except Exception:
        pass
    return {"ok": True, "platform": platform,
            "prefilled": bool(cred),
            "message": (f"Login window opening for {PLATFORMS[platform]['label']}. "
                        + ("Form will be pre-filled from your vault — just press "
                           "the sign-in button." if cred else
                           "Log in once; Jarvis reuses the session afterwards.")
                        + " Close the window when you're done.")}


def _login_window_worker(platform: str) -> None:
    from core.browser_lock import release
    meta = PLATFORMS[platform]
    _login_windows[platform] = True
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR, headless=False,
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox", "--start-maximized"])
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(meta["login_url"], wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2000)

            # Pre-fill from the vault (never auto-submit: the human presses
            # the button, which also absorbs captcha/2FA flows).
            try:
                from services.vault import get_credential
                cred = get_credential(platform)
            except Exception:
                cred = None
            if cred:
                try:
                    for sel in USERNAME_SELECTORS:
                        el = page.query_selector(sel)
                        if el:
                            el.fill(cred["username"])
                            break
                    for sel in PASSWORD_SELECTORS:
                        el = page.query_selector(sel)
                        if el:
                            el.fill(cred["password"])
                            break
                except Exception:
                    pass

            # Wait until the user closes the window (poll page liveness).
            deadline = time.time() + 15 * 60   # give up after 15 minutes
            while time.time() < deadline:
                time.sleep(2)
                try:
                    if not ctx.pages:
                        break
                    _ = ctx.pages[0].url   # raises once the browser is closed
                except Exception:
                    break
            try:
                ctx.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[session_manager] login window failed for {platform}: {e}")
    finally:
        _login_windows.pop(platform, None)
        release(f"login:{platform}")
        # Session probably changed — refresh this platform's cached status.
        with _cache_lock:
            _cache.pop(platform, None)


# ── Notifications / replies sweep ─────────────────────────────────────────────

_monitor_started = False
_monitor_lock = threading.Lock()
MONITOR_INTERVAL = 30 * 60   # seconds between inbox sweeps


def start_reply_monitor() -> None:
    """
    Background inbox monitor: every MONITOR_INTERVAL, if the user enabled it
    (settings key monitor_inbox = 'on'), sync the Freelancer inbox so Pulse can
    announce replies. Off by default — a machine that never logged in would
    otherwise burn 30s of Playwright per sweep for nothing.
    """
    global _monitor_started
    with _monitor_lock:
        if _monitor_started:
            return
        _monitor_started = True

    def _loop():
        time.sleep(120)   # let startup finish; first sweep after 2 min
        while True:
            try:
                from models.db import conn
                with conn() as db:
                    row = db.execute("SELECT value FROM settings WHERE key='monitor_inbox'"
                                     ).fetchone()
                if row and (row["value"] or "").lower() in ("on", "true", "1", "yes"):
                    from core.browser_lock import acquire, release
                    lock = acquire("reply_monitor")
                    if lock.get("ok"):
                        try:
                            check_replies()
                        finally:
                            release("reply_monitor")
            except Exception as e:
                print(f"[session_manager] reply monitor sweep failed: {e}")
            time.sleep(MONITOR_INTERVAL)

    threading.Thread(target=_loop, daemon=True, name="jarvis-reply-monitor").start()


def check_replies() -> dict:
    """
    Best-effort reply monitor: sync the Freelancer inbox into the messages
    table (reuses browser_monitor) and report how many new messages arrived.
    Called by Pulse so the user gets a proactive 'client replied' nudge.
    """
    try:
        from services.browser_monitor import sync_inbox_to_db
        new_count = sync_inbox_to_db()
        return {"ok": True, "new_messages": new_count}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
