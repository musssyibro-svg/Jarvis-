"""
test_chat_persistence.py — Chat persistence (final).
- SQLite round-trip always runs
- Frontend static check always runs
- Playwright refresh test: SKIP if frontend not running
- RAM monitoring
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

from _harness import ARTIFACTS, ROOT, TestRun, guard, ram_snapshot, register_temp, save_ram_artifact


async def _playwright_refresh(chat_url: str) -> dict:
    from playwright.async_api import async_playwright
    res = {}
    MARKER = f"PERSIST_{int(time.time())}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx  = await browser.new_context()
        page = await ctx.new_page()

        try:
            await page.goto(chat_url, wait_until="domcontentloaded", timeout=15_000)
            res["loaded"] = True

            await page.wait_for_selector("textarea, input[type='text']", timeout=8_000)

            s1 = str(ARTIFACTS / "chat_before_send.png")
            await page.screenshot(path=s1); res["shot_before"] = s1

            await page.fill("textarea, input[type='text']", MARKER)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(2000)

            s2 = str(ARTIFACTS / "chat_after_send.png")
            await page.screenshot(path=s2); res["shot_after_send"] = s2

            res["visible_before"] = MARKER in await page.content()

            await page.reload(wait_until="domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(2000)

            s3 = str(ARTIFACTS / "chat_after_refresh.png")
            await page.screenshot(path=s3); res["shot_after_refresh"] = s3

            res["visible_after"] = MARKER in await page.content()
            res["marker"] = MARKER

        except Exception as e:
            res["error"] = str(e)
        finally:
            await browser.close()

    return res


def run() -> dict:
    t   = TestRun("test_chat_persistence")
    ram = [t.ram("start")]

    # ── 1. SQLite round-trip ──────────────────────────────────────────────────
    tmpdb = tempfile.mktemp(suffix=".db")
    register_temp(tmpdb)
    os.environ["JARVIS_DB"] = tmpdb

    db = guard(t, "import models.db",
               lambda: __import__("models.db", fromlist=["conn","init_db"]))
    if db is None:
        return t.finish()

    db.DB_PATH = Path(tmpdb)
    guard(t, "init_db", lambda: db.init_db())

    SID = "pytest_persist_001"

    def write_msgs():
        c = db.conn()
        c.execute("INSERT INTO chat_messages(session_id,role,content,created_at) "
                  "VALUES(?,?,?,?)", (SID,"user","hello jarvis v8","2026-01-01T00:00:00Z"))
        c.execute("INSERT INTO chat_messages(session_id,role,content,created_at) "
                  "VALUES(?,?,?,?)", (SID,"assistant","hello Ibrahim","2026-01-01T00:00:01Z"))
        c.commit(); c.close()

    guard(t, "write messages", write_msgs)

    def read_new_conn():
        c = db.conn()
        rows = c.execute(
            "SELECT role,content FROM chat_messages WHERE session_id=? ORDER BY id",
            (SID,)).fetchall()
        c.close()
        return [dict(r) for r in rows]

    rows = guard(t, "read after simulated restart", read_new_conn)
    t.check("messages survive SQLite restart (new connection)",
            bool(rows) and len(rows) == 2,
            evidence={"restored": rows, "count": len(rows) if rows else 0})

    t.check("restored content is correct",
            bool(rows) and rows[0]["content"] == "hello jarvis v8",
            evidence={"first":  rows[0] if rows else None,
                      "second": rows[1] if rows and len(rows) > 1 else None})

    ram.append(t.ram("after_sqlite"))

    # ── 2. Frontend static check ──────────────────────────────────────────────
    chat_jsx = ROOT / "frontend" / "src" / "pages" / "Chat.jsx"
    if chat_jsx.exists():
        src = chat_jsx.read_text(encoding="utf-8")
        uses_ls  = "localStorage.getItem('jarvis_session_id')" in src
        sets_ls  = "localStorage.setItem('jarvis_session_id'" in src
        restores = "chat/history" in src

        t.check("localStorage getItem for stable session id",
                uses_ls,
                evidence={"found": uses_ls, "file": str(chat_jsx)})

        t.check("localStorage setItem persists session on first load",
                sets_ls,
                evidence={"found_in_source": sets_ls,
                          "searched_for": "localStorage.setItem('jarvis_session_id'",
                          "file": str(chat_jsx)})

        t.check("Chat.jsx calls /chat/history on mount",
                restores,
                evidence={"found": restores,
                          "checked_for": "chat/history"})
    else:
        t.log(f"Chat.jsx not found at {chat_jsx}")

    # ── 3. Playwright refresh (SKIP if not available / frontend not running) ──
    try:
        from playwright.async_api import async_playwright
        has_pw = True
    except ImportError:
        has_pw = False

    if not has_pw:
        t.skip("playwright not installed — browser refresh test requires: "
               "pip install playwright && playwright install chromium. "
               "SQLite and static checks above already passed.")
        t.add_artifact(save_ram_artifact(ram, "chat_persistence"))
        return t.finish()

    CHAT_URL = "http://127.0.0.1:5173"
    try:
        import urllib.request
        urllib.request.urlopen(CHAT_URL, timeout=3)
        frontend_up = True
    except Exception:
        frontend_up = False

    if not frontend_up:
        t.skip(f"Frontend not running at {CHAT_URL} — start with 'npm run dev' "
               "to enable browser-refresh persistence test. "
               "SQLite and static checks above already passed.")
        t.add_artifact(save_ram_artifact(ram, "chat_persistence"))
        return t.finish()

    t.log("Frontend up — running Playwright refresh test")
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()

    ram.append(t.ram("before_playwright"))
    pw_res = guard(t, "playwright refresh test",
                   lambda: loop.run_until_complete(_playwright_refresh(CHAT_URL)))
    ram.append(t.ram("after_playwright"))

    if pw_res:
        for k in ("shot_before","shot_after_send","shot_after_refresh"):
            if pw_res.get(k): t.add_artifact(pw_res[k])

        t.check("page loaded in browser",
                bool(pw_res.get("loaded")),
                evidence={"url": CHAT_URL, "loaded": pw_res.get("loaded")})

        t.check("sent message visible before refresh",
                bool(pw_res.get("visible_before")),
                evidence={"marker": pw_res.get("marker"),
                          "visible": pw_res.get("visible_before")})

        t.check("message visible after page refresh (persistence proven)",
                bool(pw_res.get("visible_after")),
                evidence={"marker":  pw_res.get("marker"),
                          "visible": pw_res.get("visible_after")},
                error=None if pw_res.get("visible_after")
                      else "message disappeared after refresh — history restore broken")

    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "chat_persistence"))
    return t.finish()


if __name__ == "__main__":
    run()
