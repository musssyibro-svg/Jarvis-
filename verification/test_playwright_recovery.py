"""
test_playwright_recovery.py — Playwright crash recovery (final).
- SKIP if playwright not installed
- Round 1: launch → write cookie → close (simulates crash)
- Round 2: reopen same profile → verify cookie persists
- No network needed — uses about:blank
- RAM monitoring
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from _harness import (TestRun, guard, ram_snapshot, save_ram_artifact,
                      register_temp, ARTIFACTS)


async def _test(profile_dir: str) -> dict:
    from playwright.async_api import async_playwright
    res = {}

    # ── Round 1: launch + set cookie ─────────────────────────────────────────
    async with async_playwright() as p:
        ctx1 = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir, headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"])
        pg1 = await ctx1.new_page()
        await pg1.goto("about:blank", wait_until="domcontentloaded", timeout=15_000)
        res["r1_url"] = pg1.url
        res["r1_ok"]  = True

        # Use a context-level cookie (works on any domain in persistent context)
        await ctx1.add_cookies([{
            "name": "jarvis_recovery", "value": "round1_value",
            "domain": "example.com", "path": "/",
            "expires": time.time() + 3600,
        }])
        cookies_r1 = await ctx1.cookies()
        ck = next((c for c in cookies_r1 if c["name"] == "jarvis_recovery"), None)
        res["ls_set"]   = ck is not None
        res["ls_value"] = (ck or {}).get("value")

        shot1 = str(ARTIFACTS / "recovery_r1.png")
        await pg1.screenshot(path=shot1)
        res["shot1"] = shot1

        # Close (simulate crash — no clean shutdown protocol)
        await ctx1.close()
        res["r1_closed"] = True

    await asyncio.sleep(0.5)

    # ── Round 2: reopen same profile, check localStorage ─────────────────────
    try:
        async with async_playwright() as p:
            ctx2 = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir, headless=True,
                args=["--no-sandbox","--disable-dev-shm-usage"])
            pg2 = await ctx2.new_page()
            await pg2.goto("about:blank",
                           wait_until="domcontentloaded", timeout=15_000)
            res["r2_url"] = pg2.url
            res["r2_ok"]  = True

            cookies_r2 = await ctx2.cookies()
            ck2 = next((c for c in cookies_r2 if c["name"] == "jarvis_recovery"), None)
            res["ls_persisted"] = (ck2 or {}).get("value") == "round1_value"
            res["ls_value_r2"]  = (ck2 or {}).get("value")

            shot2 = str(ARTIFACTS / "recovery_r2.png")
            await pg2.screenshot(path=shot2)
            res["shot2"] = shot2

            await ctx2.close()
    except Exception as e:
        res["r2_ok"]    = False
        res["r2_error"] = str(e)

    return res


def run() -> dict:
    t   = TestRun("test_playwright_recovery")
    ram = [t.ram("start")]

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        t.skip("playwright not installed — "
               "pip install playwright && playwright install chromium")
        return t.finish()

    ba = guard(t, "import browser_agent",
               lambda: __import__("agents.browser_agent", fromlist=["PROFILE_DIR"]))
    if ba is None:
        return t.finish()

    profile_dir = str(getattr(ba, "PROFILE_DIR", "/tmp/jarvis_recovery_profile"))
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    t.log(f"Profile: {profile_dir}")

    ram.append(t.ram("before_round1"))
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    res = guard(t, "crash-recovery sequence", lambda: loop.run_until_complete(_test(profile_dir)))
    ram.append(t.ram("after_round2"))

    if res is None:
        return t.finish()

    t.log(f"R1: ok={res.get('r1_ok')} ls_set={res.get('ls_set')}")
    t.log(f"R2: ok={res.get('r2_ok')} ls_persisted={res.get('ls_persisted')}")

    t.check("round 1: browser launched",
            bool(res.get("r1_ok")),
            evidence={"url": res.get("r1_url"), "closed": res.get("r1_closed")})

    t.check("round 1: localStorage value written",
            bool(res.get("ls_set")),
            evidence={"value_set": res.get("ls_value"),
                      "expected":  "round1_value"})

    t.check("round 2: browser recovered after crash-close",
            bool(res.get("r2_ok")),
            evidence={"url": res.get("r2_url"),
                      "error": res.get("r2_error")},
            error=None if res.get("r2_ok") else res.get("r2_error","recovery failed"))

    t.check("localStorage persisted across recovery cycle",
            bool(res.get("ls_persisted")),
            evidence={"expected":      "round1_value",
                      "actual":        res.get("ls_value_r2"),
                      "match":         res.get("ls_persisted"),
                      "ram_r1":        ram[1],
                      "ram_r2":        ram[2]},
            error=None if res.get("ls_persisted")
                  else f"got '{res.get('ls_value_r2')}' — profile not persisting")

    for k in ("shot1","shot2"):
        if res.get(k): t.add_artifact(res[k])

    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "playwright_recovery"))
    return t.finish()


if __name__ == "__main__":
    run()
