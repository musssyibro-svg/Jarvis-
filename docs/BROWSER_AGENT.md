# Browser Agent

`backend/agents/browser_agent.py` · `backend/core/browser_lock.py` ·
`backend/services/session_manager.py`

Playwright over a **persistent** profile: log in once by hand, reuse the session
forever.

---

## The profile is the asset

`backend/browser-profile/` holds the user's real Freelancer/QQ/Doubao logins and
the browser fingerprint. It is not a cache.

**Credentials are never typed from a config file.** The user logs in once,
manually, in a real window; Playwright keeps the session. Anything that must be
stored goes in the encrypted vault (`services/vault.py`), never in chat, never
in a workflow file, never in a log.

Profiles are split per domain — `freelance`, `research`, `desktop` — so a crash
or a Cloudflare block on one doesn't take the others down.

### What we deliberately do NOT do

An audit proposed destroying the whole context every 30 minutes to fix a memory
leak. That would throw away the logins and the fingerprint every half hour,
causing constant re-logins and *more* bot challenges.

The actual leak was **pages**, not the context: pages were opened and never
counted or closed, so a 24/7 run bloated Chromium until submissions failed. So:
pages are tracked and closed, idle pages are reaped above a cap, and the
persistent profile is never destroyed on a timer.

---

## One owner at a time — by lease, not by lock

`core/browser_lock.py`.

A plain `threading.Lock` was wrong: if the owner thread died mid-bid the browser
stayed locked forever, and the income engine logged "browser busy" until a
restart.

An audit proposed force-releasing after 5 minutes. **That is worse.** A
slow-but-alive bid submission would have the browser yanked out from under it,
and two agents would then drive the same Chrome instance — a half-submitted form
on a real freelance site.

So the owner holds a **lease it must renew** (`heartbeat()`, which the executor
does naturally as it works, `LEASE_SECONDS = 120`). Ownership is reclaimed only
when the heartbeat has genuinely stopped — the owner is dead, not merely slow.
Takeovers are recorded, so they appear in diagnostics instead of happening
invisibly.

```python
lock = acquire("bid_executor")
if not lock["ok"]:
    return {"success": False, "message": lock["message"], "busy_with": lock["busy_with"]}
try:
    ...
finally:
    release("bid_executor")
```

---

## Every action is verified

Same rule as the desktop agent: the call returning is not the action succeeding.

- **Navigation** — `wait_until="domcontentloaded"`, then confirm the URL.
  `networkidle` never fires on a page with a live SSE stream.
- **Login state** — `session_manager.is_logged_in(platform)` is checked *before*
  a submission, not after it fails. A logged-out session used to produce a
  cascade of identical failures; now it's a **skip** with `needs_login`, which
  is a different thing and says so.
- **Submission** — the page after the click is read for a confirmation, and a
  screenshot plus final URL are saved either way. See
  [FREELANCER](FREELANCER.md).

Where the site gives no confirmation, the result says **"submitted, but the page
showed no confirmation"** rather than claiming success. That distinction is the
whole point.

---

## Search from China

`tool_registry.search_url()` defaults to Bing China. Google is unreachable
without a VPN, so a search there hangs and then goes blank — and Jarvis looks
broken when the network is the problem. Configurable via the `search_engine`
setting; `google`, `bing`, `bing-cn`, `baidu`, `duckduckgo`.

Searching is done by **navigating to a search URL**, not by typing into the
browser window. Typing depends on where focus lands and whether the address bar
happens to be selected; a URL always works, and it lets a follow-on step
("…and analyze the page") run against loaded results.

## Which browser

Never hardcoded. `providers.provider_for("web_search")` returns what is actually
installed — this machine has Edge and no Chrome, and `"open browser and search
X"` used to try to launch Chrome. Enforced by `.semgrep/jarvis.yml`
(`jarvis-hardcoded-browser`).

## Scraped text is data, never instruction

Every job description Jarvis reads is untrusted content sitting next to a
logged-in browser and a shell. That is the lethal trifecta. Do not add a path
that lets scraped text reach a tool call unreviewed.

## Housekeeping

`services/maintenance.py` reaps idle pages periodically, alongside pruning the
queue, checkpointing the WAL hourly and vacuuming weekly. It runs on a schedule
rather than after every cleanup, because a VACUUM on every operation is how a
24/7 process spends its day doing nothing useful.
