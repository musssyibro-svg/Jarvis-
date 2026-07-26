# Proving Jarvis actually works — in the right order

Every review of this project ends with "run it for 24 hours." That's the right
destination and the wrong first step. A 24-hour test is a very slow way to find a
bug that shows up in thirty seconds, and when it does break at hour nine you're
reading logs trying to reconstruct what happened.

Three stages. Don't skip ahead — each one is only worth running if the previous
one was clean.

---

## Phase 0 — break it on purpose (2 minutes)

Double-click **`RUN_FAILURE_TEST.bat`**, or:

```
python tools\failure_injection.py
```

This deliberately triggers the things that WILL happen during a long run: an app
that isn't installed, no model available, a browser that dies holding the lock,
a queue with 500 rows, the emergency stop, memory pressure.

**Errors in the output are usually the correct answer.** What's being checked is
whether Jarvis fails *honestly*: notices, names the real cause, doesn't retry
what can't work, and leaves nothing wedged behind it. A test that only asked
"did it raise?" would pass a Jarvis that lies to you.

- `PASS` — failed the right way
- `FAIL` — a real bug; fix it before going further
- `SKIP` — this machine can't test that (no clipboard, no models). Not a bug.

Writes `failure_injection_report.txt`. Send that file if anything fails.

Optional: `--include-destructive` also unloads a live Ollama model. Off by
default because this is your working machine.

---

## Phase 1 — 4-hour soak, while you use the PC (half a day, unattended-ish)

Only if Phase 0 is clean.

1. Start Jarvis normally (`START_JARVIS.bat`)
2. Turn on autonomous earning, set the interval to **5 minutes** (faster than
   normal on purpose — four hours then covers what a normal day would)
3. Use your PC as you usually do. Open QQ, browse, work.

Check every 30-ish minutes on the **Diagnostics** screen:

| What | Where | Healthy |
|---|---|---|
| RAM creep | Console vitals | Steady. A slow climb that never comes back down is the finding. |
| Browser takeovers | Diagnostics → routing | Should stay at 0. Anything above 0 means an owner died mid-job. |
| Learned timings | Diagnostics → "What Jarvis has learned here" | Notepad should drop toward ~2s; QQ should rise to whatever it really needs. If nothing is learned after 4 hours, the feedback loop isn't running. |
| Failure causes | same panel | Repeating causes are your real bug list, ranked by frequency. |

The learned-timings panel is the most useful thing on that screen. It's Jarvis
telling you what it has actually measured about your machine — not a claim.

---

## Phase 2 — 24 hours unattended

Only if Phase 1 was clean.

Leave it running overnight with earning on. Kill Chrome, close QQ, and stop
Ollama at random points during the day — recovery from those is the whole point.

In the morning, download the runtime report from **Diagnostics → Download full
report**. It now includes a "learned behaviour" section: per-app success rates,
what Jarvis waits for each app, and the real causes of every recent failure with
the fix for each.

That single file is what to send when something's wrong. It beats a screenshot,
and it beats describing the symptom.

---

## What actually needs your machine

Nothing here can be checked from a Linux container, which is why it's yours to
run:

- clipboard formats (an image copied while Jarvis types)
- window focus and foreground stealing
- QQ / WeChat / Doubao launching and accepting keystrokes
- Playwright on Windows, behind the GFW
- whether memory holds up over hours

Everything else has been tested. This hasn't, and can't be.
