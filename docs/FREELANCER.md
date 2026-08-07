# Freelance income engine

`services/income_engine.py` · `agents/scout_agent.py` · `agents/score_agent.py` ·
`agents/proposal_agent.py` · `services/bid_executor.py` ·
`services/platform_meta.py` · `frontend/src/pages/Earn.jsx`

The part of Jarvis that acts under the user's name on real sites. Everything
here is built around one question: **can you prove it did what it says?**

---

## The pipeline

```
  scan → score → write → QUEUE → [you approve] → SUBMIT → receipt
```

| Status | Means |
|---|---|
| `pending` | Drafted. Nothing sent. Waiting for you. |
| `approved` | You said yes. **Still nothing sent.** |
| `executing` | Being submitted right now |
| `done` | Sent, receipt saved |
| `ready` | On a job board — apply by hand via the link. **A success, not a failure.** |
| `needs_login` | Skipped: not logged in to that platform |
| `failed` | Tried and could not |
| `rejected` | You said no |

**Approving is not submitting.** They are separate deliberate acts, and the UI
now says so. It used to emit "approved — submitting now" while submitting
nothing, which is why the user said *"I press approve all but I don't know if it
sent it"*. A false claim of action is worse than no message.

---

## Not every platform takes a bid

`services/platform_meta.py`.

| Kind | Example | What Jarvis can do |
|---|---|---|
| `bid` | Freelancer | Fill and submit a proposal |
| `board` | RemoteOK, WeWorkRemotely | Nothing on-site — apply via the link |
| `talent` | Contra, Hubstaff | Nothing — clients contact you |
| `micro` | Clickworker | Task-specific |

This gate is the fix for a cascade of `FAILED` rows. A job board has no bid form,
so a "bid" there could only ever fail — and reporting it as a failure trains you
to ignore failures. Those items become `ready`, which is a **success** state
meaning "the proposal is written, apply through the link".

Before any submission on a bid platform, `session_manager.is_logged_in()` is
checked. Logged out is a **skip** with `needs_login`, not a failure.

---

## Receipts — the point of the whole thing

Every submission saves, for success **and** failure:

```json
{
  "at": "…", "submitted_text": "the exact proposal", "job_url": "…",
  "final_url": "where it ended up", "page_title": "…",
  "proof_screenshot": "receipts/bid-20260804-190245.png",
  "confirmed_by_site": true, "outcome": "sent", "message": "…"
}
```

`GET /automation/queue/{id}/receipt` · **Proof** button on every row.

"It says it submitted" is not evidence. Without a receipt there is no way to
tell a real submission from a silent failure, and no reason to trust the engine
with anything unattended.

**`confirmed_by_site` can be `false` and that is reported as such.** When the
page shows no confirmation, the result says *"submitted, but the page showed no
confirmation — open the proof screenshot"*. Not "done".

A screenshot is captured on failure too — that's exactly when you most want to
see what the page looked like.

## "What has actually happened"

`GET /automation/queue/outcome` drives a permanent box on the Earn page:

> 3 sent (1 the site didn't confirm — check Proof) · 2 ready to apply by hand ·
> 1 blocked — not logged in

Because `POST /automation/execute-approved` starts a background thread and
returns immediately, "Executor started" told the user nothing. The page polls
every 2 seconds while submitting, 7 when idle.

---

## Cost control

`proposal_agent` writes proposals in **batches of 4** in one model call
(`BATCH_SIZE`, separated by `###PROPOSAL`), rather than one call per job — 13
calls became 4 on a machine where each one costs real seconds.

`_parse_batch()` returns `[]` on **any** mismatch between requested and returned
count, so the caller falls back to per-job generation. Slower, but every job
provably gets its own proposal. A batch that silently misaligned would put the
wrong proposal on the wrong job, under the user's name.

`score_agent` filters before `proposal_agent` runs, so no model time is spent
writing for jobs that were never worth bidding on.

## Not running twice at once

`agents/scheduler.py` guards cycles with a `threading.Event`, released in a
`finally`. `orchestrator_core` waits up to 90 s for an in-flight workflow rather
than instant-failing — instant-fail is why the log said "Cycle #N done (FAILED)"
whenever a manual scan overlapped a scheduled one, when nothing was wrong.

The browser lock is a heartbeat lease. See [BROWSER_AGENT](BROWSER_AGENT.md).

## Safety

- Nothing is submitted without approval, unless the user ticks `auto_submit`.
- `bid_executor` refuses any row not already `approved`. There is no code path
  that sets `approved` automatically.
- Logins are a persistent browser profile the user signed into by hand, or the
  encrypted vault. Never a config file.
- Job descriptions are **untrusted text**. They are read next to a logged-in
  browser; no path lets them reach a tool call unreviewed.

## Trying it without doing it

`simulate.earning()` — which sites it would search, how many proposals it would
write, whether it would submit. Scans nothing, sends nothing. In chat:
`simulate applying for jobs`.
