"""
services/fiverr_service.py
Fiverr inbox monitoring via Playwright + AI reply/offer generation.
"""

import asyncio
import sys
import traceback
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EDGE_USER_DATA = str(BASE_DIR / "browser-profile")

FIVERR_INBOX = "https://www.fiverr.com/inbox"
FIVERR_GIGS  = "https://www.fiverr.com/users/{username}/manage_gigs"


def _run_in_new_loop(coro):
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Inbox scrape ─────────────────────────────────────────────────────────────

async def _fetch_fiverr_inbox() -> list[dict]:
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
            await page.goto(FIVERR_INBOX, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(4)

            thread_sels = [
                ".conversation-list .conversation-item",
                "[class*='conversation-item']",
                ".inbox-item",
                "li[class*='inbox']",
            ]
            threads = []
            for sel in thread_sels:
                threads = await page.query_selector_all(sel)
                if threads:
                    break

            for th in threads[:25]:
                try:
                    name_el = await th.query_selector(
                        ".username, .buyer-name, [class*='username'], [class*='name']"
                    )
                    buyer = (await name_el.inner_text()).strip() if name_el else "Unknown Buyer"

                    preview_el = await th.query_selector(
                        ".last-message, .message-preview, [class*='preview'], [class*='last-message']"
                    )
                    preview = (await preview_el.inner_text()).strip() if preview_el else ""

                    gig_el = await th.query_selector(
                        ".gig-title, [class*='gig'], .order-title"
                    )
                    gig_title = (await gig_el.inner_text()).strip() if gig_el else ""

                    link_el = await th.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else ""
                    thread_url = (
                        f"https://www.fiverr.com{href}"
                        if href and href.startswith("/")
                        else (href or FIVERR_INBOX)
                    )

                    messages.append({
                        "buyer_name":      buyer,
                        "gig_title":       gig_title,
                        "message_preview": preview[:200],
                        "full_message":    preview,
                        "thread_url":      thread_url,
                        "received_at":     datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    continue
        except Exception as exc:
            print(f"[FiverrMonitor] {exc}")
            traceback.print_exc()
        finally:
            await ctx.close()
    return messages


def fetch_fiverr_inbox() -> list[dict]:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run_in_new_loop, _fetch_fiverr_inbox()).result(timeout=120)
    except Exception as exc:
        print(f"[FiverrMonitor] fetch failed: {exc}")
        return []


# ── Sync to DB ───────────────────────────────────────────────────────────────

def sync_fiverr_inbox() -> int:
    from models.db import conn
    from services.deepseek_service import call_model

    messages = fetch_fiverr_inbox()
    new_count = 0
    now = datetime.now(timezone.utc).isoformat()

    with conn() as db:
        for msg in messages:
            exists = db.execute(
                "SELECT id FROM fiverr_messages WHERE buyer_name=? AND message_preview=?",
                (msg["buyer_name"], msg["message_preview"]),
            ).fetchone()
            if exists:
                continue

            reply_draft = _gen_reply(msg["buyer_name"], msg["full_message"])
            db.execute(
                """INSERT INTO fiverr_messages
                   (buyer_name, gig_title, message_preview, full_message, thread_url,
                    is_read, reply_draft, received_at, created_at)
                   VALUES (?,?,?,?,?,0,?,?,?)""",
                (
                    msg["buyer_name"], msg["gig_title"], msg["message_preview"],
                    msg["full_message"], msg["thread_url"],
                    reply_draft, msg["received_at"], now,
                ),
            )
            new_count += 1

    return new_count


# ── AI helpers ────────────────────────────────────────────────────────────────

def _gen_reply(buyer: str, message: str) -> str:
    from services.deepseek_service import call_model

    prompt = f"""
A Fiverr buyer named "{buyer}" sent this message:
---
{message}
---
Write a professional, friendly Fiverr seller reply. Under 120 words.
Output ONLY the reply text.
""".strip()
    return call_model(prompt, fast=True)


def generate_custom_offer(buyer: str, message: str, gig_title: str) -> str:
    from services.deepseek_service import call_model

    prompt = f"""
A Fiverr buyer named "{buyer}" is interested in: {gig_title}
Their message: {message}

Write a custom Fiverr offer message. Include:
- Acknowledgment of their specific need
- What you will deliver
- Suggested price range and timeline
- Call to action to accept the offer

Under 150 words. Output ONLY the offer text.
""".strip()
    return call_model(prompt)
