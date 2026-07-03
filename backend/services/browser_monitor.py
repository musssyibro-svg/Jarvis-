"""
services/browser_monitor.py
Monitor Freelancer inbox using Browser Use / Playwright.
Stores new messages in the DB and generates reply drafts via DeepSeek.
"""

import asyncio
import sys
import traceback
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EDGE_USER_DATA = str(BASE_DIR / "browser-profile")

INBOX_URL = "https://www.freelancer.com/messages/inbox"


def _run_in_new_loop(coro):
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _fetch_inbox() -> list[dict]:
    """Scrape the Freelancer inbox and return a list of message dicts."""
    from playwright.async_api import async_playwright

    messages = []
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=EDGE_USER_DATA,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        page = await ctx.new_page()
        try:
            await page.goto(INBOX_URL, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(4)

            # Try multiple selector patterns for inbox threads
            thread_sels = [
                ".MessageList-item",
                ".inbox-message",
                "[class*='message-item']",
                "app-message-list-item",
            ]
            threads = []
            for sel in thread_sels:
                threads = await page.query_selector_all(sel)
                if threads:
                    break

            for th in threads[:20]:
                try:
                    sender_el = await th.query_selector(
                        ".MessageList-sender, .sender-name, [class*='sender']"
                    )
                    sender = (await sender_el.inner_text()).strip() if sender_el else "Unknown"

                    preview_el = await th.query_selector(
                        ".MessageList-preview, .message-preview, [class*='preview']"
                    )
                    preview = (await preview_el.inner_text()).strip() if preview_el else ""

                    link_el = await th.query_selector("a[href*='/messages/']")
                    thread_url = ""
                    if link_el:
                        href = await link_el.get_attribute("href")
                        thread_url = (
                            f"https://www.freelancer.com{href}"
                            if href and href.startswith("/")
                            else (href or "")
                        )

                    messages.append(
                        {
                            "sender": sender,
                            "message_preview": preview[:200],
                            "full_message": preview,
                            "thread_url": thread_url,
                            "received_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                except Exception:
                    continue
        except Exception as exc:
            print(f"[InboxMonitor] Error: {exc}")
            traceback.print_exc()
        finally:
            await ctx.close()

    return messages


def fetch_inbox_messages() -> list[dict]:
    """Public sync entry point. Returns list of message dicts."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run_in_new_loop, _fetch_inbox())
            return future.result(timeout=120)
    except Exception as exc:
        print(f"[InboxMonitor] fetch_inbox_messages failed: {exc}")
        return []


def sync_inbox_to_db() -> int:
    """Fetch inbox, save new messages to DB, generate reply drafts. Returns count of new msgs."""
    from models.db import conn
    from services.deepseek_service import generate_reply_draft

    messages = fetch_inbox_messages()
    new_count = 0
    now = datetime.now(timezone.utc).isoformat()

    with conn() as db:
        for msg in messages:
            # Avoid duplicates by sender + preview
            exists = db.execute(
                "SELECT id FROM messages WHERE sender=? AND message_preview=?",
                (msg["sender"], msg["message_preview"]),
            ).fetchone()
            if exists:
                continue

            reply_draft = generate_reply_draft(msg["sender"], msg["full_message"])
            db.execute(
                """INSERT INTO messages
                   (sender, message_preview, full_message, received_at, thread_url,
                    is_read, reply_draft, created_at)
                   VALUES (?,?,?,?,?,0,?,?)""",
                (
                    msg["sender"],
                    msg["message_preview"],
                    msg["full_message"],
                    msg["received_at"],
                    msg["thread_url"],
                    reply_draft,
                    now,
                ),
            )
            new_count += 1

    print(f"[InboxMonitor] Saved {new_count} new messages")
    return new_count
