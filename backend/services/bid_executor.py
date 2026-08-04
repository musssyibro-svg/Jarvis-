"""
services/bid_executor.py
Executes APPROVED automation_queue items.

Flow per item:
  1. Item must have status='approved' (set by human in the Queue UI)
  2. Open the job's Freelancer URL using the SAME persistent browser
     context as browser_agent (login-once, reuse-forever)
  3. Locate the bid form (description textarea + amount + period if present)
  4. Fill description with payload.application (the AI-written proposal)
  5. Click "Place Bid" / submit
  6. On success: mark queue item 'done', create/update a row in `proposals`
     with status='sent' so MemoryAgent can track win/loss later
  7. On failure: mark queue item 'failed' with an error note, emit to feed

Every step emits to the orchestrator's live feed (STATE.emit) so the
dashboard shows real-time progress: "Opening job page...", "Filling bid
form...", "Bid submitted ✓", etc.

SAFETY: This module NEVER runs on its own. It only acts on queue rows
that a human has already moved to status='approved' via the UI. There is
no code path that sets status='approved' automatically.
"""
import asyncio
import json
import threading
from datetime import datetime, timezone

from agents.browser_agent import _get_context, _new_loop
from agents.orchestrator import STATE
from models.db import conn

_executor_lock = threading.Lock()
_executor_running = False


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── Core bid-fill logic (Playwright) ─────────────────────────────────────────

async def _submit_bid_async(job_url: str, proposal_text: str, headless: bool = True) -> dict:
    """
    Navigate to a Freelancer project page and submit a bid.
    Returns {"success": bool, "message": str, "screenshot": optional path}
    """
    ctx  = await _get_context(headless=headless)
    page = await ctx.new_page()
    await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

    try:
        STATE.emit("executor", f"Opening job page: {job_url[:60]}…")
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45_000)
        await asyncio.sleep(2.5)

        if "login" in page.url.lower():
            return {"success": False, "message":
                    "NOT_LOGGED_IN — use Freelance ▸ Auto Mode ▸ Platform Logins "
                    "(or POST /sessions/open-login/freelancer) to log in once; "
                    "Jarvis reuses that session afterwards"}

        # Try to open the bid form if it's behind a button
        BID_BUTTON_SELECTORS = [
            "button:has-text('Place a Bid')",
            "button:has-text('Bid Now')",
            "a:has-text('Place a Bid')",
            "[data-qa-bid-button]",
            ".PlaceBidButton",
        ]
        for sel in BID_BUTTON_SELECTORS:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(1.5)
                    STATE.emit("executor", "Opened bid form")
                    break
            except Exception:
                continue

        # Locate description textarea
        STATE.emit("executor", "Filling bid description…")
        DESC_SELECTORS = [
            "textarea[name='description']",
            "textarea[data-qa-description-input]",
            "textarea.BidDescription",
            "textarea[placeholder*='message' i]",
            "textarea[placeholder*='proposal' i]",
            "textarea",
        ]
        desc_box = None
        for sel in DESC_SELECTORS:
            desc_box = await page.query_selector(sel)
            if desc_box:
                break

        if not desc_box:
            return {"success": False, "message": "Could not find bid description field — bid form layout may have changed. Manual submission required."}

        await desc_box.click()
        await desc_box.fill("")
        await desc_box.type(proposal_text, delay=4)
        await asyncio.sleep(0.5)

        # Optional: bid amount / period fields — leave Freelancer defaults
        # if present, since we don't have a target amount from the queue payload.
        # Submitting with platform-suggested defaults is acceptable; the human
        # already reviewed the proposal text before approving.

        STATE.emit("executor", "Locating submit button…")
        SUBMIT_SELECTORS = [
            "button[type='submit']:has-text('Place Bid')",
            "button:has-text('Place Bid')",
            "button:has-text('Submit')",
            "[data-qa-submit-bid]",
            "button.btn-place-bid",
        ]
        submit_btn = None
        for sel in SUBMIT_SELECTORS:
            submit_btn = await page.query_selector(sel)
            if submit_btn:
                break

        if not submit_btn:
            return {"success": False, "message": "Filled proposal text but could not find submit button. Bid NOT submitted — review manually."}

        STATE.emit("executor", "Clicking submit…")
        await submit_btn.click()
        await asyncio.sleep(3)

        # Heuristic success check: URL change, success toast, or bid list update
        success_indicators = [
            "bid placed", "bid submitted", "your bid", "successfully",
        ]
        page_text = (await page.content()).lower()

        # PROOF. "It said it submitted" is not evidence, and the user is right
        # to distrust it: a screenshot of the page after the click, plus the URL
        # we ended on, is the only thing that shows what actually reached the
        # site. Captured for success AND failure — a failed submit is exactly
        # when you most want to see what the page looked like.
        proof = await _capture_proof(page)

        if any(ind in page_text for ind in success_indicators) or "manage" in page.url.lower():
            STATE.emit("executor", "Bid submitted - proof saved", "success")
            return {"success": True, "message": "Bid submitted", "confirmed": True,
                    **proof}

        STATE.emit("executor", "Submitted, but the site did not confirm it - "
                               "check the proof screenshot", "warning")
        return {"success": True, "confirmed": False,
                "message": "Submitted, but the page showed no confirmation. "
                           "Open the proof screenshot to see what happened.",
                **proof}

    except Exception as e:
        STATE.emit("executor", f"Error: {e}", "error")
        proof = {}
        try:
            proof = await _capture_proof(page)
        except Exception:
            pass
        return {"success": False, "message": str(e), **proof}
    finally:
        await page.close()


async def _capture_proof(page) -> dict:
    """
    Save what the page actually looked like, and where we ended up.

    Without this the only record of a submission is Jarvis's own claim that it
    worked. That is precisely the thing the user cannot verify and should not
    have to take on trust.
    """
    out = {}
    try:
        out["final_url"] = page.url
        out["page_title"] = (await page.title())[:120]
    except Exception:
        pass
    try:
        from datetime import datetime as _dt
        from pathlib import Path as _P
        shots = _P(__file__).resolve().parent.parent / "screenshots" / "receipts"
        shots.mkdir(parents=True, exist_ok=True)
        name = f"bid-{_dt.now().strftime('%Y%m%d-%H%M%S')}.png"
        await page.screenshot(path=str(shots / name), full_page=False)
        out["proof_screenshot"] = f"receipts/{name}"
    except Exception as e:
        out["proof_error"] = str(e)[:100]
    return out


def _run_submit(job_url: str, proposal_text: str, headless: bool = True) -> dict:
    """Run the async submit in a fresh event loop (Windows-safe)."""
    import concurrent.futures
    loop = _new_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(loop.run_until_complete, _submit_bid_async(job_url, proposal_text, headless)).result(timeout=120)


# ── Queue execution ────────────────────────────────────────────────────────────

def execute_queue_item(qid: int, headless: bool = True) -> dict:
    """
    Execute a single APPROVED queue item.
    Safe to call repeatedly — re-checks status before acting.
    V9 Constraint 4: acquires the single-owner browser lock; if another workflow
    holds it, returns 'browser busy' immediately rather than racing the context.
    """
    from core.browser_lock import acquire, release
    lock = acquire("bid_executor")
    if not lock.get("ok"):
        return {"success": False, "message": lock.get("message", "Browser busy"),
                "busy_with": lock.get("busy_with")}
    try:
        return _execute_queue_item_locked(qid, headless)
    finally:
        release("bid_executor")


def _execute_queue_item_locked(qid: int, headless: bool = True) -> dict:
    with conn() as db:
        row = db.execute("SELECT * FROM automation_queue WHERE id=?", (qid,)).fetchone()

    if not row:
        return {"success": False, "message": "Queue item not found"}

    item = dict(row)
    if item["status"] != "approved":
        return {"success": False, "message": f"Item status is '{item['status']}', not 'approved' — refusing to execute"}

    try:
        payload = json.loads(item.get("payload") or "{}")
    except Exception:
        payload = {}

    job          = payload.get("job", {})
    proposal_txt = payload.get("application", "")
    job_url      = job.get("link") or job.get("url") or ""
    platform     = item.get("platform", "")

    # ── Platform-kind gate — the root fix for the RemoteOK FAILED cascade ───────
    # RemoteOK / WeWorkRemotely / Remote.co are job BOARDS: there is no on-site
    # bid form to fill, so a "bid" there could only ever fail. Talent platforms
    # (Contra/Hubstaff/Fiverr) don't take bids either. For all of these, mark the
    # item 'ready' (a SUCCESS state meaning "apply externally"), attach the link
    # and note — never 'failed'.
    from services import platform_meta
    if not platform_meta.submittable(platform):
        note = platform_meta.apply_note(platform)
        with conn() as db:
            db.execute("UPDATE automation_queue SET status='ready',processed_at=? WHERE id=?",
                       (_now(), qid))
        STATE.emit("executor",
                   f"'{item['job_title'][:45]}' is on a {platform_meta.KIND_LABEL[platform_meta.kind(platform)]} — "
                   f"proposal ready, apply via the job link", "info")
        return {"success": True, "status": "ready", "external": True,
                "message": note or "Ready to apply externally", "link": job_url}

    # Bid platform: the session MUST be valid before we try, or we get the
    # logged-out failure cascade. Validate first; skip (not fail) if logged out.
    try:
        from services import session_manager
        logged = session_manager.is_logged_in(platform)
    except Exception:
        logged = None
    if logged is False:
        with conn() as db:
            db.execute("UPDATE automation_queue SET status='needs_login',processed_at=? WHERE id=?",
                       (_now(), qid))
        STATE.emit("executor",
                   f"Skipped '{item['job_title'][:45]}' — not logged in to {platform}. "
                   f"Log in via Platform Logins, then re-submit.", "warning")
        return {"success": False, "status": "needs_login",
                "message": f"Not logged in to {platform} — log in and retry"}

    if not job_url:
        with conn() as db:
            db.execute("UPDATE automation_queue SET status='failed',processed_at=? WHERE id=?", (_now(), qid))
        STATE.emit("executor", f"No job URL for '{item['job_title']}' — marked failed", "error")
        return {"success": False, "message": "Missing job URL"}

    if not proposal_txt:
        with conn() as db:
            db.execute("UPDATE automation_queue SET status='failed',processed_at=? WHERE id=?", (_now(), qid))
        STATE.emit("executor", f"No proposal text for '{item['job_title']}' — marked failed", "error")
        return {"success": False, "message": "Missing proposal text"}

    STATE.emit("executor", f"Executing approved bid: {item['job_title'][:50]}")
    with conn() as db:
        db.execute("UPDATE automation_queue SET status='executing',processed_at=? WHERE id=?", (_now(), qid))

    result = _run_submit(job_url, proposal_txt, headless=headless)
    now = _now()

    # Keep the receipt with the queue item: what was sent, where it landed, and
    # a screenshot. This is what turns "it says it did it" into something you
    # can actually check.
    payload["receipt"] = {
        "at": now,
        "submitted_text": proposal_txt,
        "job_url": job_url,
        "final_url": result.get("final_url"),
        "page_title": result.get("page_title"),
        "proof_screenshot": result.get("proof_screenshot"),
        "confirmed_by_site": result.get("confirmed"),
        "outcome": "sent" if result.get("success") else "failed",
        "message": result.get("message", ""),
    }

    if result.get("success"):
        with conn() as db:
            db.execute("UPDATE automation_queue SET status='done',processed_at=?,payload=? "
                       "WHERE id=?", (now, json.dumps(payload), qid))

            # Create/update a proposals row so MemoryAgent tracks this bid
            existing = db.execute(
                "SELECT id FROM proposals WHERE job_id=? AND platform=?",
                (item.get("job_id"), item.get("platform"))
            ).fetchone()

            if existing:
                db.execute(
                    "UPDATE proposals SET status='sent',proposal_text=?,updated_at=? WHERE id=?",
                    (proposal_txt, now, existing["id"])
                )
            else:
                db.execute(
                    """INSERT INTO proposals
                       (job_id,platform,job_title,job_desc,budget,job_link,
                        proposal_text,status,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (item.get("job_id"), item.get("platform"), item.get("job_title"),
                     job.get("description",""), job.get("budget",""), job_url,
                     proposal_txt, "sent", now, now)
                )
        STATE.emit("executor", f"✓ Done: {item['job_title'][:50]}", "success")
    else:
        with conn() as db:
            db.execute("UPDATE automation_queue SET status='failed',processed_at=?,payload=? "
                       "WHERE id=?", (now, json.dumps(payload), qid))
        STATE.emit("executor", f"✗ Failed: {item['job_title'][:50]} — {result.get('message','')}", "error")

    return result


def execute_all_approved(headless: bool = True) -> dict:
    """
    Process every queue item currently marked 'approved'.
    Runs sequentially in a background thread so the live feed stays smooth.
    """
    global _executor_running
    with _executor_lock:
        if _executor_running:
            return {"message": "Executor already running"}
        _executor_running = True

    def _worker():
        global _executor_running
        try:
            with conn() as db:
                rows = db.execute("SELECT id FROM automation_queue WHERE status='approved' ORDER BY id ASC").fetchall()
            ids = [r["id"] for r in rows]
            STATE.emit("executor", f"Starting execution of {len(ids)} approved item(s)")
            for qid in ids:
                # Re-check running flag each loop in case user wants to stop
                if not _executor_running:
                    break
                execute_queue_item(qid, headless=headless)
            STATE.emit("executor", "Execution batch complete")
        finally:
            with _executor_lock:
                _executor_running = False

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"message": "Executor started"}


def stop_executor():
    global _executor_running
    with _executor_lock:
        _executor_running = False
    STATE.emit("executor", "Stop requested — will halt after current item")
    return {"message": "Stop requested"}


def executor_status() -> dict:
    with _executor_lock:
        running = _executor_running
    with conn() as db:
        approved  = db.execute("SELECT COUNT(*) c FROM automation_queue WHERE status='approved'").fetchone()["c"]
        executing = db.execute("SELECT COUNT(*) c FROM automation_queue WHERE status='executing'").fetchone()["c"]
        done      = db.execute("SELECT COUNT(*) c FROM automation_queue WHERE status='done'").fetchone()["c"]
        failed    = db.execute("SELECT COUNT(*) c FROM automation_queue WHERE status='failed'").fetchone()["c"]
    return {"running": running, "approved": approved, "executing": executing, "done": done, "failed": failed}
