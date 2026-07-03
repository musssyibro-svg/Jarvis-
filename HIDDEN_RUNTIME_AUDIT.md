# Jarvis V8.5 — Hidden Runtime Failure Audit
Scope: circular imports, desktop Windows risks, Ollama RAM on 16GB,
ScoutAgent live-scraping, 24h uptime stability. Code patches only where severe.

================================================================================
SEVERITY RANKING (production-breaking first)
================================================================================

## CRITICAL

### C1 — RAM exhaustion: deepseek-r1 + llava cannot coexist on 16GB
Area 3. Real memory math on a 16GB Windows box:
  - OS + apps baseline:            ~4-5 GB
  - qwen2.5:0.5b resident:         ~0.6 GB
  - deepseek-r1:1.5b resident:     ~1.5-2 GB
  - llava:7b resident:             ~5-6 GB (plus ~1-2GB working set for image)
  Chat (deepseek) + a vision call (llava) at the same time = ~4.5GB models on
  top of a ~5GB baseline + Chromium (see C2) easily pushes 13-15GB. Windows
  starts swapping to disk -> multi-second to multi-minute stalls, and Ollama
  may hard-fail a model load with a runtime error mid-request.
  MITIGATION ALREADY PRESENT: vision() holds _large_lock and calls _unload()
  (keep_alive=0) after each call, and LARGE_MODELS={llava}. So llava is loaded
  on demand and evicted. This is correct and meaningfully reduces the risk.
  RESIDUAL RISK: deepseek-r1 is NOT in LARGE_MODELS, so it stays resident with
  keep_alive default (5 min). If a vision call fires while deepseek is warm and
  Chromium is open, peak can still exceed RAM. Severity stays CRITICAL because
  the failure (OOM/swap) is silent and user-facing as a "hang".
  RECOMMENDED (not auto-applied — your call): set OLLAMA_KEEP_ALIVE short, or
  add deepseek to a "unload before vision" step.

### C2 — Stale persistent browser context across 24h uptime
Area 5 + Area 2. browser_agent keeps a module-global `_ctx` persistent Chromium
context (launch_persistent_context) reused "forever". bid_executor reuses the
SAME context. Over 24h:
  - Chromium memory creeps (renderer leaks, accumulated tabs/pages). Each call
    opens a page; _check_login closes its page, but failure paths may not.
  - If Chromium crashes or the profile lock goes stale, _ctx is a dead handle;
    nothing detects this or relaunches -> every subsequent browser/bid action
    fails until restart.
  - No idle timeout, no periodic recycle.
  Severity CRITICAL for an always-on autonomous agent: after hours of running,
  bidding/browsing silently stops working with no self-heal.

## HIGH

### H1 — ScoutAgent has no per-platform timeout or retry; one slow site stalls a scan
Area 4. scout_agent wraps scans in bare `except Exception` (good for not
crashing) but there is no explicit network timeout passed to the platform
scrapers and no retry/backoff. Failure modes on live sites:
  - Cloudflare / captcha: returns an HTML challenge page -> 0 jobs, logged as
    "jobs=0" (the diagnostic logging from Goal 7 helps identify this).
  - Rate limiting (HTTP 429): no backoff -> repeated hammering, possible IP ban.
  - A hung TCP connection with no timeout can block the scan thread for the
    socket default (can be minutes), making AutoMode look frozen.
  Severity HIGH: scans appear to hang or silently return nothing; with the
  scheduler (every N min) a slow site can overlap the next run.

### H2 — Scheduler can overlap runs if a pipeline takes longer than the interval
Area 5. scheduler.py ticks schedule.run_pending() every 1s; the job calls
start_pipeline(config). If interval=1min but a scan+propose cycle takes >1min
(very likely with 6 platforms + Ollama generation), the next tick starts
another pipeline while the first is still running. No "is a run already
active?" guard. Result over 24h: stacked concurrent pipelines, multiplied RAM
(see C1), DB write contention, duplicate queue items.
  Severity HIGH: compounds C1 and queue growth; emerges only under real timing.

### H3 — automation_queue grows unbounded except for manual 'clear done'
Area 5. Queue rows are inserted by every pipeline run. They are only removed by
DELETE on explicit user action (delete item / clear done). 'failed' and
'pending' rows are never auto-pruned. Over 24h of scheduled runs with login-
required platforms failing, 'failed' rows accumulate indefinitely; the queue
read does `LIMIT ?` so the UI stays responsive, but the table grows without
bound and approval views fill with stale failures.
  Severity HIGH for 24h autonomous operation; not user-visible immediately.

## MEDIUM

### M1 — keyboard global hotkey for emergency stop is NOT registered
Area 2. desktop_agent sets pyautogui.FAILSAFE (mouse to corner aborts the
current pyautogui call) and exposes emergency_stop()/_emergency_stop Event,
but there is NO OS-level global keyboard hook (the `keyboard` lib is not used
to bind a panic hotkey). Consequence: if a runaway loop is firing input, the
only physical kill switches are (a) slam mouse to top-left corner (works only
during a pyautogui call, between PAUSE gaps) or (b) hit the API/UID estop —
which requires the UI to be responsive. There is no always-on hardware-level
abort key.
  Severity MEDIUM: FAILSAFE covers the common case; the gap is the
  "UI frozen + input storm" corner case.

### M2 — _require() emergency-stop gate covers INPUT but not file destructive ops
Area 2. _require() (estop+pyautogui check) guards mouse/keyboard funcs. The
file ops (delete_file/move_file) are intentionally allowed during estop (so you
can clean up), which is reasonable — but it means engaging emergency stop does
NOT halt an in-progress destructive file operation. Documented here so it's a
conscious decision, not a surprise.
  Severity MEDIUM / by-design; flagging for awareness.

### M3 — pyautogui requires an interactive desktop session; fails as a service
Area 2. If Jarvis is ever launched as a Windows service / scheduled task with
no logged-in interactive session, pyautogui has no screen to drive and every
input action throws. The code degrades (HAS_PYAUTOGUI / _require), so it won't
crash, but desktop control silently no-ops. Severity MEDIUM: only bites if run
headless; fine for normal desktop launch.

================================================================================
AREAS THAT PASSED (no production risk found)
================================================================================

### Area 1 — Circular imports: CLEAN (no cycles)
Import graph (top-level edges):
  main.py            -> routes.* , (lazy) agents via routers
  agents.commander   -> agents.orchestrator (STATE), agents.memory_agent   [top]
                     -> agents.desktop_agent, agents.vision_agent           [lazy, in-function]
  agents.orchestrator-> (lazy) scout/score/memory/proposal agents
  routes.agents      -> (lazy) agents.commander, agents.desktop_agent, vision
  agents.planner     -> (lazy) services.deepseek_service
  agents.memory_agent-> models.db only (NO back-edge to commander/orchestrator)
  agents.desktop_agent-> stdlib + pyautogui only (NO agent imports)

  Key fact: orchestrator does NOT import commander; memory_agent does NOT import
  commander or orchestrator. The one top-level edge (commander->orchestrator) is
  one-directional. All risky edges are lazy (in-function), which breaks any
  potential cycle at import time. Cold import of commander, orchestrator, and
  planner all succeed. No circular import exists.

### Emergency stop coverage: COMPLETE for input
  All 8 input functions (move, click, drag, scroll, type_text, type_text_raw,
  hotkey, press) call _require() at the top, which checks _emergency_stop
  (a threading.Event, thread-safe) before any pyautogui call. Verified per-fn.

### llava RAM containment: CORRECT
  vision() loads llava under _large_lock and unloads (keep_alive=0) in a finally
  block. Only one large-model session at a time. This is the right pattern.

================================================================================
RECOMMENDED FIX PRIORITY (if you choose to patch)
================================================================================
1. H2 scheduler overlap guard — cheapest, highest 24h payoff (a single
   "if pipeline running: skip this tick" flag). Prevents C1 amplification.
2. C2 browser context health-check + recycle — detect dead _ctx, relaunch;
   add periodic close/reopen.
3. H1 scout per-platform timeout (e.g. 20s) + 429 backoff.
4. H3 auto-prune automation_queue (cap rows or age out 'failed').
5. C1 evict deepseek before vision / shorten keep_alive.
None auto-applied — per your instruction, code patches only if you approve,
since none are crash-on-start severe (all are degradation-over-time or
load-dependent).
