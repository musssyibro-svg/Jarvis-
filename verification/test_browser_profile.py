"""
test_browser_profile.py — Persistent Playwright profile (final).
- SKIP if Playwright not installed or no network
- Creates cookie in session 1, restarts context, verifies cookie in session 2
- RAM monitoring
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from _harness import (TestRun, guard, ram_snapshot, save_ram_artifact,
                      register_temp, ARTIFACTS)

TEST_URL    = "https://example.com"
COOKIE_NAME = "jarvis_v8_test"
COOKIE_VAL  = "persistence_proof"


async def _cookie_test(profile_dir: str) -> dict:
    from playwright.async_api import async_playwright

    res = {}

    async with async_playwright() as p:
        ctx1 = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir, headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"])
        pg = await ctx1.new_page()
        await pg.goto(TEST_URL, wait_until="domcontentloaded", timeout=30_000)
        res["title_s1"] = await pg.title()

        await ctx1.add_cookies([{
            "name": COOKIE_NAME, "value": COOKIE_VAL,
            "domain": "example.com", "path": "/",
            "expires": time.time() + 86_400,
        }])
        cookies = await ctx1.cookies()
        ck = next((c for c in cookies if c["name"] == COOKIE_NAME), None)
        res["set_ok"]    = ck is not None
        res["set_value"] = (ck or {}).get("value")

        shot1 = str(ARTIFACTS / "browser_session1.png")
        await pg.screenshot(path=shot1)
        res["shot1"] = shot1
        await ctx1.close()

    await asyncio.sleep(0.5)

    async with async_playwright() as p:
        ctx2 = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir, headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"])
        pg2 = await ctx2.new_page()
        await pg2.goto(TEST_URL, wait_until="domcontentloaded", timeout=30_000)
        cookies2 = await ctx2.cookies()
        ck2 = next((c for c in cookies2 if c["name"] == COOKIE_NAME), None)
        res["persisted_ok"]    = ck2 is not None
        res["persisted_value"] = (ck2 or {}).get("value")
        res["match"]           = (ck2 or {}).get("value") == COOKIE_VAL

        shot2 = str(ARTIFACTS / "browser_session2.png")
        await pg2.screenshot(path=shot2)
        res["shot2"] = shot2
        await ctx2.close()

    return res


def _run(profile_dir: str) -> dict:
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_cookie_test(profile_dir))
    finally:
        loop.close()


def run() -> dict:
    t   = TestRun("test_browser_profile")
    ram = [t.ram("start")]

    ba = guard(t, "import browser_agent",
               lambda: __import__("agents.browser_agent", fromlist=["PROFILE_DIR"]))
    if ba is None:
        return t.finish()

    profile_dir = str(getattr(ba, "PROFILE_DIR", ""))
    t.log(f"PROFILE_DIR = {profile_dir}")
    t.check("PROFILE_DIR configured",
            bool(profile_dir) and len(profile_dir) > 3,
            evidence={"PROFILE_DIR": profile_dir})

    # SKIP if playwright not installed
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        t.skip("playwright not installed — "
               "pip install playwright && playwright install chromium")
        return t.finish()

    # SKIP if no network
    try:
        import urllib.request
        urllib.request.urlopen(TEST_URL, timeout=5)
    except Exception as e:
        t.skip(f"No network ({e}) — browser cookie test needs internet access")
        return t.finish()

    ram.append(t.ram("before_browser"))
    res = guard(t, "cookie persistence test", lambda: _run(profile_dir))
    ram.append(t.ram("after_browser"))

    if res is None:
        return t.finish()

    t.log(f"Session 1 title: {res.get('title_s1')}  cookie set: {res.get('set_ok')}")
    t.log(f"Session 2 persisted: {res.get('persisted_ok')}  match: {res.get('match')}")

    t.check("page loaded in session 1",
            bool(res.get("title_s1")),
            evidence={"title": res.get("title_s1"), "url": TEST_URL})

    t.check("cookie written in session 1",
            bool(res.get("set_ok")),
            evidence={"cookie_name": COOKIE_NAME,
                      "cookie_value": res.get("set_value")})

    t.check("cookie persists after context restart",
            bool(res.get("match")),
            evidence={"expected":  COOKIE_VAL,
                      "actual":    res.get("persisted_value"),
                      "match":     res.get("match"),
                      "ram_delta": {
                          "before_mb": ram[-2].get("used_mb"),
                          "after_mb":  ram[-1].get("used_mb"),
                      }},
            error=None if res.get("match")
                  else f"expected '{COOKIE_VAL}' got '{res.get('persisted_value')}'")

    for k in ("shot1","shot2"):
        if res.get(k):
            t.add_artifact(res[k])

    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "browser_profile"))
    return t.finish()


if __name__ == "__main__":
    run()
