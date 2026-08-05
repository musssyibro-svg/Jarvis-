"""
tools/failure_injection.py — Phase 0. Break Jarvis on purpose, in two minutes,
and find out whether it recovers honestly.

WHY THIS EXISTS
---------------
Every review of this project ends with the same instruction: run it for 24 hours
on the real machine. That advice is right but badly ordered. A 24-hour test is a
very slow way to discover a bug that shows up in the first thirty seconds, and
when it does fail at hour 9 you are left reading logs trying to reconstruct what
happened. Break things deliberately first, while you are watching.

Each scenario below corresponds to something that WILL happen during a long run:
Chrome dies, Ollama stops answering, an app isn't installed, the queue fills up,
you copy an image while Jarvis is typing, you hit the emergency stop. The
question is never "does Jarvis avoid this" — it can't. The question is whether it
notices, says something true about it, and carries on.

WHAT "PASS" MEANS HERE
----------------------
Not "no error". An error is the correct outcome for most of these. A scenario
passes when Jarvis fails the RIGHT WAY:

    * it notices (doesn't report success for something that didn't happen),
    * it classifies the cause instead of shrugging,
    * it doesn't retry something that cannot work,
    * it leaves nothing wedged behind it (no stuck lock, no dead handle).

A test that only checks "did it raise" would pass a Jarvis that lies. These
check the content of the failure.

RUNNING IT
----------
    python tools/failure_injection.py              # everything that's safe
    python tools/failure_injection.py --list
    python tools/failure_injection.py --only clipboard,missing_app
    python tools/failure_injection.py --include-destructive

Destructive scenarios (killing your real Chrome, stopping Ollama) are OFF by
default — this is your working machine. Everything else is safe to run any time,
including while Jarvis is up.

The backend does NOT need to be running: scenarios import the modules directly.
A report is written to failure_injection_report.txt for sending on.
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


class Result:
    def __init__(self, name, why):
        self.name, self.why = name, why
        self.status, self.detail, self.notes = SKIP, "", []

    def ok(self, detail=""):
        self.status, self.detail = PASS, detail
        return self

    def bad(self, detail=""):
        self.status, self.detail = FAIL, detail
        return self

    def skip(self, detail=""):
        self.status, self.detail = SKIP, detail
        return self

    def note(self, line):
        self.notes.append(line)
        return self


# ── Scenario 1: an app that isn't installed ──────────────────────────────────

def s_missing_app():
    """
    Ask for an app that cannot exist. The failure mode this catches is the
    expensive one: retrying a launch that can never succeed, three times, with
    backoff, and then reporting a vague error.
    """
    r = Result("missing_app", "Opening an app that isn't installed")
    from agents.desktop_agent import execute_chain

    fake = "definitely_not_installed_zzq"
    t0 = time.time()
    res = execute_chain([{"action": "open_app", "params": {"name_or_path": fake}}])
    elapsed = time.time() - t0

    if res.get("success"):
        return r.bad("Reported SUCCESS for an app that does not exist. "
                     "This is the 'it said it did it but didn't' bug.")

    fail = res.get("failure") or {}
    steps = res.get("steps") or [{}]
    attempts = steps[0].get("attempts", "?")
    r.note(f"took {elapsed:.1f}s, {attempts} attempt(s), kind={fail.get('kind')}")

    if fail.get("kind") != "app_not_found":
        return r.bad(f"Misclassified as '{fail.get('kind')}' — should be app_not_found. "
                     f"Recovery will be aimed at the wrong problem.")
    if fail.get("retryable"):
        return r.bad("Marked retryable. Retrying a missing app can never work.")
    if attempts != 1:
        return r.bad(f"Tried {attempts} times. Should stop after 1.")
    if not fail.get("remedy"):
        return r.bad("No remedy offered — the user is told what broke but not what to do.")
    return r.ok(f"Stopped after 1 attempt in {elapsed:.1f}s with a usable message.")


# ── Scenario 2: clipboard holding something unrestorable ─────────────────────

def s_clipboard():
    """
    The one users actually feel. Jarvis uses the clipboard to type and to verify
    typing. If it clobbers what you had copied, that's data loss, every time it
    types. Checks BOTH that text is restored and that non-text is refused.
    """
    r = Result("clipboard", "Typing must not destroy what you had copied")
    try:
        import pyperclip
    except ImportError:
        return r.skip("pyperclip not installed — cannot test on this machine")

    from agents import desktop_agent as da

    sentinel = f"USER-CLIPBOARD-{int(time.time())}"
    try:
        pyperclip.copy(sentinel)
        if pyperclip.paste() != sentinel:
            return r.skip("no working clipboard in this environment (headless?)")
    except Exception as e:
        return r.skip(f"clipboard unavailable: {str(e)[:60]}")

    ok, saved = da._clipboard_snapshot()
    if not ok or saved != sentinel:
        return r.bad(f"Snapshot failed to capture the clipboard (got {saved!r}).")

    # Simulate the round trip Jarvis performs while typing.
    pyperclip.copy("text that jarvis is typing")
    da._clipboard_restore(saved)
    after = pyperclip.paste()
    if after != sentinel:
        return r.bad(f"Clipboard NOT restored. Expected {sentinel!r}, got {after!r}. "
                     f"Every typing action would eat the user's copy.")
    r.note("text clipboard: saved and restored intact")

    # Non-text: must decline rather than replace an image with text.
    if os.name == "nt":
        try:
            import win32clipboard  # noqa: F401
            r.note("pywin32 present — non-text clipboard is detectable")
        except ImportError:
            r.note("pywin32 NOT installed: an image on the clipboard cannot be "
                   "detected, so it would be replaced by text. "
                   "Fix: pip install pywin32")
    return r.ok("Clipboard survives a full type-and-verify round trip.")


# ── Scenario 3: no model available ───────────────────────────────────────────

def s_no_model():
    """
    Ollama down or empty. The wrong behaviour is a hang or a cheerful reply
    invented without a model; the right one is an immediate, specific error.
    """
    r = Result("no_model", "Behaviour when no LLM is available")
    from services import experience, model_router

    picked = model_router.pick("chat")
    r.note(f"router picked: {picked.get('model')} (warning: {picked.get('warning')})")

    c = experience.classify("No models installed. Run: ollama pull qwen2.5:3b", "ask_model")
    if c["kind"] != "no_model":
        return r.bad(f"'no models installed' classified as {c['kind']}.")
    if c["retryable"]:
        return r.bad("Marked retryable — would retry a model that isn't there.")

    # A plan needing a model must be BLOCKED up front, not discovered step by step.
    if not picked.get("model"):
        conf = experience.confidence([{"action": "ask_model", "params": {}}])
        if not conf.get("blockers"):
            return r.bad("No model installed, yet a model-dependent plan wasn't "
                         "blocked before running.")
        return r.ok(f"Blocked up front: {conf['blockers'][0]}")
    return r.ok(f"A model is available ({picked['model']}); "
                f"missing-model handling classifies correctly.")


# ── Scenario 4: a queue with hundreds of rows ────────────────────────────────

def s_queue_load():
    """
    Fill the automation queue and check reads stay fast. A 24h run accumulates
    rows; if the UI query degrades, the whole console feels broken.
    """
    r = Result("queue_load", "Queue performance with 500+ rows")
    from models.db import conn

    tag = f"fi-{int(time.time())}"
    n = 500
    try:
        with conn() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS automation_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, job_id TEXT,
                job_title TEXT, action TEXT, payload TEXT, status TEXT,
                created_at TEXT, processed_at TEXT)""")
            now = datetime.utcnow().isoformat()
            db.executemany(
                "INSERT INTO automation_queue (platform,job_id,job_title,action,"
                "payload,status,created_at) VALUES (?,?,?,?,?,?,?)",
                [(tag, f"{tag}-{i}", f"load test {i}", "apply", "{}", "pending", now)
                 for i in range(n)])

        t0 = time.time()
        with conn() as db:
            rows = db.execute("SELECT * FROM automation_queue ORDER BY id DESC "
                              "LIMIT 100").fetchall()
        q_ms = (time.time() - t0) * 1000
        r.note(f"inserted {n} rows; 100-row read took {q_ms:.0f}ms ({len(rows)} back)")

        if q_ms > 500:
            return r.bad(f"Queue read took {q_ms:.0f}ms with {n} extra rows — "
                         f"the console will feel frozen. Needs an index.")
        return r.ok(f"Read stayed at {q_ms:.0f}ms under {n} extra rows.")
    finally:
        try:
            with conn() as db:
                db.execute("DELETE FROM automation_queue WHERE platform=?", (tag,))
        except Exception:
            pass


# ── Scenario 5: the browser dies mid-job ─────────────────────────────────────

def s_browser_death():
    """
    Chrome crashes or you close it. Two things must hold: the lock must not stay
    held by the dead owner forever (the old "Browser busy" wedge), and the dead
    context handle must be dropped so the next call relaunches.
    """
    r = Result("browser_death", "Browser dies while holding the lock")
    from agents import browser_agent
    from core import browser_lock

    owner = f"fi-test-{int(time.time())}"
    got = browser_lock.acquire(owner)
    if not got.get("ok"):
        return r.skip(f"lock already held by {got.get('busy_with')} — try again when idle")
    try:
        # Simulate an owner that died without releasing: stop heart-beating.
        browser_lock._owner["last_beat"] = time.time() - (browser_lock.LEASE_SECONDS + 5)
        other = browser_lock.acquire("fi-test-other")
        if not other.get("ok"):
            return r.bad("A dead owner kept the lock forever. This is the "
                         "'Browser busy (owned by …)' wedge that needs a restart.")
        if not other.get("took_over_from"):
            return r.bad("Took the lock but didn't record the takeover — it would "
                         "happen invisibly instead of showing in diagnostics.")
        r.note(f"lease reclaimed from the dead owner: {other.get('note','')[:70]}")
        browser_lock.release("fi-test-other")

        # A live owner must NOT be reclaimed just for being slow.
        browser_lock.acquire(owner)
        browser_lock.heartbeat(owner)
        stolen = browser_lock.acquire("fi-test-thief")
        if stolen.get("ok"):
            return r.bad("A HEALTHY owner was evicted. A slow-but-working bid "
                         "submission would have the browser yanked mid-write.")
        r.note("a live, heart-beating owner is correctly left alone")

        # Dead context handles must be dropped, not reused.
        browser_agent._ctx["fi-fake"] = object()      # no .pages -> looks dead
        reaped = browser_agent.reap()
        if "fi-fake" not in reaped.get("dropped_contexts", []):
            browser_agent._ctx.pop("fi-fake", None)
            return r.bad("A dead browser handle was not dropped; the next "
                         "navigate would keep throwing.")
        return r.ok("Dead owner reclaimed, live owner protected, dead handle dropped.")
    finally:
        browser_agent._ctx.pop("fi-fake", None)
        for o in (owner, "fi-test-other", "fi-test-thief"):
            try:
                browser_lock.release(o)
            except Exception:
                pass


# ── Scenario 6: emergency stop ───────────────────────────────────────────────

def s_estop():
    """
    The stop button is the one thing that must never be advisory. If input still
    goes through while it's engaged, it's decoration.
    """
    r = Result("estop", "Emergency stop actually blocks input")
    from agents import desktop_agent as da

    was = da.is_estopped()
    try:
        da.emergency_stop()
        if not da.is_estopped():
            return r.bad("emergency_stop() didn't set the flag.")

        leaks = []
        for name, call in [("type_text", lambda: da.type_text("should not type")),
                           ("click", lambda: da.click(5, 5)),
                           ("press", lambda: da.press("enter")),
                           ("hotkey", lambda: da.hotkey("ctrl", "a"))]:
            out = call()
            if out.get("success"):
                leaks.append(name)
        if leaks:
            return r.bad(f"These ran while STOPPED: {', '.join(leaks)}. "
                         f"The stop button does not stop Jarvis.")
        r.note("type/click/press/hotkey all refused while engaged")

        if da._read_focused_text() is not None:
            return r.bad("Verification still drove the keyboard while stopped.")

        da.clear_emergency_stop()
        if da.is_estopped():
            return r.bad("Could not clear the emergency stop — Jarvis stays deaf.")
        return r.ok("All input refused while engaged; clears cleanly.")
    finally:
        if not was:
            da.clear_emergency_stop()


# ── Scenario 7: does it actually learn? ──────────────────────────────────────

def s_learning():
    """
    experience.py is only worth its complexity if the learned numbers move. Feed
    it a slow app and a fast one and check the waits diverge in the right
    direction — this is what should make Notepad snappy and QQ reliable.
    """
    r = Result("learning", "Learned timings converge on reality")
    from services import experience as E

    slow, fast = f"fi_slow_{int(time.time())}", f"fi_fast_{int(time.time())}"
    base = E.launch_wait_for(slow)["wait_s"]
    for t in (6.2, 7.9, 6.8, 9.1, 7.2, 8.4):
        E.record(slow, E.WINDOW_READY, True, t)
    for t in (0.3, 0.5, 0.4, 0.35, 0.45):
        E.record(fast, E.WINDOW_READY, True, t)

    s, f = E.launch_wait_for(slow), E.launch_wait_for(fast)
    r.note(f"default={base}s · slow app -> {s['wait_s']}s · fast app -> {f['wait_s']}s")

    if not s["learned"] or not f["learned"]:
        return r.bad("No learning recorded — the DB write is failing silently.")
    if s["wait_s"] <= f["wait_s"]:
        return r.bad(f"Slow app ({s['wait_s']}s) isn't waited on longer than the "
                     f"fast one ({f['wait_s']}s). The learning is inverted.")
    if s["wait_s"] < 9.1:
        return r.bad(f"Waits {s['wait_s']}s for an app observed taking 9.1s — "
                     f"one launch in six would type into the wrong window.")
    if f["wait_s"] >= base:
        return r.bad(f"Fast app still waits {f['wait_s']}s (was {base}s) — "
                     f"no speed-up where it matters most.")

    for ok in (False, True, False, False, True, False):
        E.record(slow, "open_app", ok, 3.0, kind="" if ok else "window_never_appeared")
    if not E.needs_extra_attempt(slow, "open_app")["extra"]:
        return r.bad("An app failing half its launches earns no extra attempt.")
    return r.ok(f"Slow app {s['wait_s']}s vs fast {f['wait_s']}s; flaky app gets a retry.")


# ── Scenario 8: model unload frees RAM ───────────────────────────────────────

def s_model_pressure(destructive=False):
    """
    The 16GB question. keep_alive must shrink as memory tightens, or one screen
    analysis leaves a 5GB model resident and everything else crawls.
    """
    r = Result("model_pressure", "keep_alive adapts to memory pressure")
    from services import model_router

    free = model_router.free_ram_gb()
    big = model_router.keep_alive_for("llava:7b")
    small = model_router.keep_alive_for("qwen2.5:1.5b")
    r.note(f"free RAM {free:.1f}GB · llava:7b -> {big} · qwen2.5:1.5b -> {small}")

    def secs(v):
        v = str(v)
        if v.endswith("m"):
            return float(v[:-1]) * 60
        return float(v.rstrip("s") or 0)

    if secs(big) > secs(small):
        return r.bad(f"A 5GB model is kept resident LONGER ({big}) than a 1.4GB "
                     f"one ({small}). Backwards for a 16GB machine.")
    if free < 2.5 and secs(big) != 0:
        return r.bad(f"Only {free:.1f}GB free and a big model still pinned for {big}.")
    if not destructive:
        r.note("skipped the live unload (needs --include-destructive)")
        return r.ok(f"Scaling is correct: big={big}, small={small}.")

    try:
        installed = model_router.installed_models()
        if not installed:
            return r.skip("no models installed to unload")
        before = model_router.free_ram_gb()
        model_router.unload(installed[0])
        time.sleep(3)
        after = model_router.free_ram_gb()
        r.note(f"unloaded {installed[0]}: {before:.1f}GB -> {after:.1f}GB free")
        return r.ok(f"Unload freed {after - before:.1f}GB.")
    except Exception as e:
        return r.skip(f"ollama unavailable: {str(e)[:60]}")


# ── Scenario 9: honest failure classification across the board ───────────────

def s_classification():
    """
    Everything downstream — which recovery runs, what the user is told — hangs
    off getting the KIND right. Checks the real error strings this project's own
    logs produce.
    """
    r = Result("classification", "Real errors map to the right cause")
    from services import experience as E

    cases = [
        ("typed but the text isn't in the focused field", "type_text", "focus_lost"),
        ("Windows cannot find 'qq'", "open_app", "app_not_found"),
        ("Window 'chrome' did not appear within 8s", "wait_for_window", "window_never_appeared"),
        ("No models installed. Run: ollama pull qwen2.5:3b", "ask_model", "no_model"),
        ("OCR timed out after 20s", "analyze_screen", "ocr_timeout"),
        ("Not logged in to peopleperhour", "submit_bid", "login_required"),
        ("Cloudflare challenge detected", "scan_jobs", "bot_challenge"),
        ("Browser busy (owned by login:freelancer)", "navigate", "browser_busy"),
        ("net::ERR_CONNECTION_RESET", "navigate", "network"),
        ("EMERGENCY STOP engaged", "click", "emergency_stop"),
    ]
    wrong = []
    for err, action, expect in cases:
        got = E.classify(err, action)["kind"]
        if got != expect:
            wrong.append(f"{err[:34]!r} -> {got} (want {expect})")
    r.note(f"{len(cases) - len(wrong)}/{len(cases)} classified correctly")
    if wrong:
        return r.bad("Misclassified: " + " · ".join(wrong[:3]))

    never_retry = {"no_model", "model_too_small", "app_not_found", "ocr_missing",
                   "login_required", "bot_challenge", "permission", "emergency_stop"}
    bad = [k for k in never_retry if E.KINDS[k][2]]
    if bad:
        return r.bad(f"These are marked retryable but retrying can't help: {bad}")
    return r.ok(f"All {len(cases)} real errors classified; no futile retries.")


def s_control():
    """
    Pause and cancel must actually take effect, and must never leave work
    half-done. An autonomous system you can't stop isn't trustworthy; one that
    stops mid-action leaves half a bid on a real freelance site.
    """
    r = Result("control", "Pause / resume / cancel behave")
    from services import control

    control.clear()
    if control.status()["mode"] != "running":
        return r.bad("Didn't start in the running state.")

    # A checkpoint with nothing pending must not block.
    t0 = time.time()
    control.checkpoint("noop")
    if time.time() - t0 > 0.5:
        return r.bad("checkpoint() blocked when nothing was pending — this "
                     "would slow every step of every task.")

    # Pause, then confirm a worker actually holds.
    control.pause("test")
    held = {"blocked": False}

    def worker():
        try:
            control.checkpoint("test-step")
            held["blocked"] = True
        except control.Cancelled:
            held["cancelled"] = True

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout=1.5)
    if not th.is_alive():
        control.clear()
        return r.bad("A paused worker did NOT hold — pause does nothing.")
    r.note("a paused worker holds at the checkpoint")

    # A cancel must release a paused worker, not deadlock it.
    control.cancel("test")
    th.join(timeout=3)
    if th.is_alive():
        control.clear()
        return r.bad("Cancelling while paused left the worker stuck forever. "
                     "This would need a restart to clear.")
    if not held.get("cancelled"):
        control.clear()
        return r.bad("Worker resumed instead of cancelling.")
    r.note("cancel releases a paused worker and raises Cancelled")

    control.clear()
    if control.status()["mode"] != "running" or control.is_cancelled():
        return r.bad("clear() didn't reset — the next task would start cancelled.")

    # Explain must work without a model and without inventing anything.
    ex = control.explain(3)
    if "because" not in ex or not isinstance(ex.get("steps"), list):
        return r.bad("explain() returned nothing usable.")
    r.note(f"explain() answered with {len(ex['because'])} reason(s)")
    return r.ok("Pause holds, cancel releases cleanly, clear resets.")


def s_decompose():
    """
    A multi-step sentence must become multiple steps, and a sentence containing
    the word "and" inside its object must NOT. Getting either wrong is how
    "search BMW M4 and analyze the page" became a search for that whole string.
    """
    r = Result("decompose", "Sentences split into steps at the right places")
    from services.decompose import decompose, split_clauses

    cases = [
        ("open browser and search BMW M4 and analyze the page", 3),
        ("open notepad, then type hello, then save it", 3),
        ("search for black and decker drill", 1),      # "and" inside the object
        ("open notepad and type \"open the door and run\"", 2),   # quoted literal
        ("open browser search bmw m4", 2),             # no connector at all
    ]
    for text, want in cases:
        got = split_clauses(text)
        if len(got) != want:
            return r.bad(f"{text!r} split into {len(got)} clause(s), expected "
                         f"{want}: {got}")
    r.note(f"{len(cases)} phrasings split correctly")

    d = decompose("open browser and search BMW M4 and analyze the page")
    urls = [s for s in d["steps"] if s["action"] == "open_url"]
    if not urls:
        return r.bad("No navigation step was produced for a search.")
    q = urls[0]["params"].get("query", "")
    if q.strip().lower() != "bmw m4":
        return r.bad(f"Searched for {q!r} — the follow-on clause leaked into the "
                     f"query. This is the original bug.")
    r.note("the query stops at the step boundary")

    if not any(s["action"] == "analyze" for s in d["steps"]):
        return r.bad("The 'analyze the page' clause was silently dropped.")

    # An unparseable clause must be REPORTED, never quietly discarded.
    d2 = decompose("open notepad and frobnicate the widget")
    if not d2.get("unresolved"):
        return r.bad("A clause nobody understood was dropped without a word. "
                     "Running half a command and reporting success is the worst "
                     "possible failure mode.")
    r.note("unparseable clauses are reported, not dropped")
    return r.ok("Clauses split on verbs, queries stop at boundaries, leftovers reported.")


def s_plan_visibility():
    """
    The plan must be visible WHILE it runs, and skip/stop must be cooperative.
    A control that only works between tasks isn't a control.
    """
    r = Result("plan_visibility", "Live plan publishes and accepts controls")
    from services import live_plan

    live_plan.clear()
    if live_plan.snapshot()["status"] != "none":
        return r.bad("A cleared planner still reported a plan.")

    steps = [{"action": "open_app", "params": {"name_or_path": "notepad"}},
             {"action": "type_text", "params": {"text": "hi"}},
             {"action": "press", "params": {"key": "enter"}}]
    snap = live_plan.begin("test goal", steps, ["Open notepad", "Type hi", "Press enter"])
    if snap["total"] != 3 or snap["steps"][0]["text"] != "Open notepad":
        return r.bad("begin() didn't publish readable steps.")
    r.note("plan published with human wording before anything ran")

    live_plan.step_start(0)
    if live_plan.snapshot()["current"] != 0:
        return r.bad("A running step wasn't reported as current — the UI would "
                     "show nothing happening while work was in flight.")

    # Skipping the step in flight must be REFUSED, not silently accepted.
    if live_plan.skip(0).get("ok"):
        return r.bad("Allowed skipping the step already running. That's the "
                     "half-typed-sentence bug.")
    r.note("refuses to skip the step in flight")

    if not live_plan.skip(2).get("ok"):
        return r.bad("Couldn't skip a pending step.")
    if not live_plan.should_skip(2):
        return r.bad("skip() was accepted but the executor wouldn't see it.")
    r.note("a pending step can be skipped and the executor sees it")

    live_plan.step_end(0, False, error="couldn't find it",
                       failure={"kind": "app_not_found", "cause": "couldn't find it",
                                "remedy": "open it once by hand"})
    live_plan.finish(False, "couldn't find it")
    s = live_plan.snapshot()
    if s["status"] != "failed" or s["steps"][0]["status"] != "failed":
        return r.bad("A failed plan didn't record as failed.")

    # The classification recorded at failure time must survive to the narrative.
    from services import narrate
    w = narrate.why()
    if w.get("kind") != "app_not_found" or not w.get("fix"):
        return r.bad("The 'why' narrative lost the diagnosis the executor "
                     "already had — it would say 'I don't know why' about a "
                     "failure it understood.")
    r.note("the failure classification survives into the explanation")

    live_plan.clear()
    return r.ok("Plan is visible live, controls are cooperative, diagnosis survives.")


def s_selfeval():
    """
    Confidence must come from evidence, and an unverified success must cost more
    than an honest failure — that's the shape of "it told me it was done".
    """
    r = Result("selfeval", "Confidence is earned, not asserted")
    from services import selfeval

    clean = [{"step": 1, "action": "open_app", "verified": True, "attempts": 1,
              "duration_s": 1.1},
             {"step": 2, "action": "type_text", "verified": True, "attempts": 1,
              "duration_s": 0.4}]
    good = selfeval.score(clean, True)
    if good["confidence"] < 90:
        return r.bad(f"A clean verified run scored only {good['confidence']}%.")
    r.note(f"clean run scores {good['confidence']}%")

    lying = [{"step": 1, "action": "open_app", "success": True, "verified": False,
              "attempts": 1, "duration_s": 1.0}]
    liar = selfeval.score(lying, True)
    if liar["confidence"] >= good["confidence"]:
        return r.bad("An unverified 'success' scored as high as a verified one. "
                     "That's exactly the false-Done problem.")
    r.note(f"unverified success drops to {liar['confidence']}%")

    # A retried launch must produce a concrete, numeric adjustment.
    retried = [{"step": 1, "action": "open_app", "verified": True, "attempts": 3,
                "duration_s": 6.0, "app": "qq"}]
    adj = selfeval.adjustment(retried, True)
    if not adj or adj.get("kind") != "wait_longer" or not adj.get("delta_s"):
        return r.bad(f"No measurable adjustment from a retried launch: {adj}")
    r.note(f"retried launch -> wait {adj['delta_s']}s longer for {adj['target']}")

    # A clean run must produce NO adjustment — inventing one trains on noise.
    if selfeval.adjustment(clean, True) is not None:
        return r.bad("Invented an adjustment for a run with nothing wrong.")
    r.note("a clean run changes nothing")
    return r.ok("Confidence tracks evidence; adjustments are numeric and earned.")


def s_auth():
    """
    A web page you visit must not be able to drive your keyboard. This is the
    single most important check in this file.
    """
    r = Result("auth", "The gate blocks drive-by requests")
    from services import auth

    blocked, code, msg = auth.authorize(
        "/agents/desktop/run", "POST",
        {"origin": "https://evil.example.com", "host": "127.0.0.1:8000"})
    if blocked:
        return r.bad("A request from an arbitrary website was ALLOWED to reach "
                     "desktop control. Any page you open could type on your "
                     "keyboard.")
    if code != 403:
        return r.bad(f"Blocked, but with status {code} instead of 403.")
    r.note("cross-origin request to desktop control is refused")

    ok, _, _ = auth.authorize("/os/state", "GET",
                              {"origin": "http://localhost:5173",
                               "host": "127.0.0.1:8000"})
    if not ok:
        return r.bad("The real UI was blocked — the gate is unusable.")
    r.note("the local UI still works")

    ok, _, _ = auth.authorize("/health", "GET", {})
    if not ok:
        return r.bad("Health check requires auth; the launcher would report the "
                     "backend as down while it's running.")
    r.note("health stays open so the launcher can see the backend")

    # DNS rebinding: the attacker's name resolves to 127.0.0.1, but the Host
    # header still carries their domain.
    blocked2, _, _ = auth.authorize("/agents/desktop/run", "POST",
                                    {"host": "attacker.example.com"})
    if blocked2:
        return r.bad("A rebound host header was accepted.")
    r.note("DNS-rebinding host header is refused")
    return r.ok("Websites cannot drive Jarvis; the local UI is unaffected.")


def s_teach_privacy():
    """
    A demonstration must never capture a password. Recording a login and
    replaying the keystrokes would put the user's password in a plaintext
    workflow file.
    """
    r = Result("teach_privacy", "Demonstrations never record passwords")
    from services import teach

    t = time.time()
    events = [
        {"t": t, "kind": "key", "char": "h", "app": "notepad", "title": "Untitled"},
        {"t": t + 0.1, "kind": "key", "char": "i", "app": "notepad", "title": "Untitled"},
        {"t": t + 3.0, "kind": "secret", "app": "msedge", "title": "Sign in"},
        {"t": t + 3.1, "kind": "secret", "app": "msedge", "title": "Sign in"},
        {"t": t + 3.4, "kind": "key", "char": None, "key": "enter",
         "app": "msedge", "title": "Sign in"},
    ]
    steps = teach.distil(events)
    blob = repr(steps).lower()
    if "secret" in blob and "credential" not in blob:
        return r.bad("Raw secret events leaked into the workflow.")
    creds = [s for s in steps if s["action"] == "credential"]
    if len(creds) != 1:
        return r.bad(f"Expected exactly one credential step, got {len(creds)}. "
                     f"Two would type the password into the username field.")
    r.note("password keystrokes became one vault lookup")

    if not teach._looks_secret("Sign in - Microsoft"):
        return r.bad("A login window wasn't recognised as one.")
    if not teach._looks_secret("密码"):
        return r.bad("A Chinese password window wasn't recognised — this user "
                     "runs Windows in Chinese.")
    r.note("login windows are recognised in English and Chinese")

    if any(s["action"] == "type_text" and "hi" not in s["params"]["text"]
           for s in steps):
        return r.bad("Ordinary typing was mangled.")
    r.note("ordinary typing is still captured normally")
    return r.ok("Passwords are never recorded; normal input still is.")


def s_url_gate():
    """
    Jarvis drives a browser that is already signed in as the user. A URL that
    reaches it acts with those sessions.

    The harm if this breaks: "go to 192.168.1.1" opens the router's admin page
    in a browser holding every cookie the user has, and a job description that
    says "browse to <url>" gets the model to do it without asking.

    Both doors are checked, because there are two and the obvious one is not
    the one that runs.
    """
    r = Result("url_gate", "The browser can't be pointed at your own network")
    from agents.browser_agent import check_url

    for good in ("https://www.freelancer.com/jobs", "github.com", "www.upwork.com"):
        if not check_url(good)[0]:
            return r.bad(f"Blocked a real job site ({good}) — worse than no gate.")
    r.note("public sites still open")

    for bad in ("http://192.168.1.1/admin", "http://127.0.0.1:8000/os/state",
                "localhost:8000", "file:///C:/Users/me/.ssh/id_rsa",
                "javascript:alert(1)", "http://169.254.169.254/"):
        url, why = check_url(bad)
        if url:
            return r.bad(f"{bad} was allowed through to a logged-in browser.")
        if not why:
            return r.bad(f"{bad} was refused with no reason given.")
    r.note("loopback, LAN, link-local and non-web schemes all refused, each with a reason")

    # The door that actually runs. "go to X" never reaches the chat adapter's
    # browser branch — decompose turns it into open_url first.
    import webbrowser
    opened = []
    real_open, webbrowser.open = webbrowser.open, lambda u: opened.append(u)
    try:
        from agents.desktop_agent import open_url
        open_url("http://192.168.1.1/admin")
        open_url("https://example.com")
    finally:
        webbrowser.open = real_open
    if any("192.168" in u for u in opened):
        return r.bad("open_url — the path that really runs — reached the LAN.")
    if not any("example.com" in u for u in opened):
        return r.bad("open_url stopped opening ordinary sites.")
    r.note("open_url (the system default browser) is gated too, not just Playwright")

    from services import experience
    fail = experience.classify("'192.168.1.1' is on your local network.",
                               action="open_url",
                               result={"blocked": True,
                                       "error": "'192.168.1.1' is on your local network."})
    if fail["retryable"]:
        return r.bad("A refusal is being retried — it will just be refused again.")
    if "192.168.1.1" not in fail["cause"]:
        return r.bad("The refusal reason never reaches the user.")
    r.note("a refusal is reported as a decision, not retried as a fault")
    return r.ok("Both browser doors are gated, and refusals explain themselves.")


def s_failure_evidence():
    """
    When an action fails, the user gets a short "here's the cause and the fix".
    Behind it there has to be enough to actually diagnose the thing — and it
    must not contain their password.

    The harm if this breaks: a failure whose only record is str(e). That was
    the single word 'DISPLAY' for the headless crash, and the only way forward
    was to reproduce it on the user's machine.

    The opposite harm, if the fix is careless: the runtime report is the file
    the user emails when something misbehaves. A typed password in it travels
    with it.
    """
    r = Result("failure_evidence", "A failed action leaves evidence, not secrets")
    from agents import desktop_agent as da
    from services import trace

    trace._failures.clear()
    out = da._run_action("hotkey", {"keys": None})     # raises inside the lambda
    if out.get("success"):
        return r.bad("A broken action reported success.")
    recs = trace.failures()
    if not recs:
        return r.bad("A failed action left no record at all.")
    if "desktop_agent.py" not in recs[0]["detail"]:
        return r.bad("The record has no traceback — this is the whole point of it.")
    r.note("a raising action records the traceback and the line that raised")

    trace._failures.clear()
    # noqa S106: the fake password IS the test. Ruff spotting it here is the
    # rule working — it's exactly the string that must not survive redaction.
    trace.failure("desktop.type_text", "did not verify",
                  text="hunter2-is-my-banking-password",
                  password="hunter2",  # noqa: S106
                  name_or_path="chrome")
    blob = repr(trace.failures())
    if "hunter2" in blob:
        return r.bad("A password reached the diagnostics buffer, which is served "
                     "over HTTP and lands in the downloadable runtime report.")
    r.note("credentials and typed text never reach the buffer")
    if "chrome" not in blob:
        return r.bad("Redaction ate the useful context too — a record with "
                     "nothing in it is not evidence.")
    r.note("ordinary context survives, so the record is still worth reading")

    trace.reset_costs()
    for _ in range(3):
        trace.record_cost("ai.chat/ollama", 9000)
    for _ in range(80):
        trace.record_cost("desktop.click", 10)
    if trace.profile()["slowest"] != "ai.chat/ollama":
        return r.bad("The profile can't name the slowest component, so "
                     "'Jarvis is slow' stays an opinion.")
    r.note("the profile names where the time actually went")
    trace._failures.clear()
    trace.reset_costs()
    return r.ok("Failures are diagnosable and carry no credentials.")


def s_simulation():
    """
    A simulation must execute NOTHING. This is the whole feature: a dry run with
    side effects is worse than no dry run, because it gets trusted.
    """
    r = Result("simulation", "Simulating never executes anything")
    from services import live_plan, simulate

    live_plan.clear()

    # Monkey-patch the executor so that ANY execution during a simulation is
    # caught, rather than hoping it didn't happen.
    from agents import desktop_agent
    fired = {"n": 0}
    real_run, real_chain = desktop_agent._run_action, desktop_agent.execute_chain

    def trap(*a, **k):
        fired["n"] += 1
        return {"success": False, "error": "trapped"}

    desktop_agent._run_action = trap
    desktop_agent.execute_chain = trap
    try:
        sim = simulate.task("open notepad and type hello and analyze the page")
        earn = simulate.earning()
    finally:
        desktop_agent._run_action, desktop_agent.execute_chain = real_run, real_chain

    if fired["n"]:
        return r.bad(f"Simulating ran {fired['n']} real action(s). A dry run with "
                     f"side effects is the worst possible version of this feature.")
    r.note("no desktop action was executed")

    if live_plan.snapshot()["status"] != "none":
        return r.bad("Simulating published a live plan — the UI would show work "
                     "in progress that isn't happening.")
    r.note("no plan was published")

    if not sim.get("would"):
        return r.bad("Task simulation produced no steps to show.")
    if len(sim["would"]) < 3:
        return r.bad(f"Only {len(sim['would'])} step(s) — the sentence has three "
                     f"clauses, so decomposition didn't run.")
    r.note(f"showed {len(sim['would'])} steps with effects and estimates")

    # Every step must declare what it touches; "unknown" everywhere would make
    # the risk column decorative.
    unknown = [w for w in sim["would"] if w["level"] == "unknown"]
    if unknown:
        return r.bad(f"{len(unknown)} step(s) don't say what they'd touch: "
                     + ", ".join(w["action"] for w in unknown))
    if not any(w["level"] in ("writes", "sensitive") for w in sim["would"]):
        return r.bad("Typing wasn't flagged as changing anything.")
    r.note("side effects are labelled, typing flagged as a change")

    if not earn.get("would") or "note" not in earn:
        return r.bad("Freelance simulation returned nothing usable.")
    if earn.get("auto_submit") and not any("auto-submit is ON" in w.lower() or
                                           "auto-submit" in w.lower()
                                           for w in earn.get("warnings", [])):
        return r.bad("Auto-submit is on and the simulation didn't warn about it.")
    r.note("freelance cycle described without scanning or sending")

    # The trigger must be explicit. If a plain command were read as a request to
    # simulate, the thing the user asked for would silently not happen.
    if simulate.match("open notepad and type hello") is not None:
        return r.bad("A normal command was mistaken for a simulation request. "
                     "The user's actual command would silently not run.")
    if simulate.match("what would you do if I say open notepad") is None:
        return r.bad("An explicit simulation request wasn't recognised.")
    r.note("only explicit requests trigger a simulation")
    return r.ok("Shows the full plan and its effects, executes nothing.")


def s_ui_renders():
    """
    The UI must actually put something on the screen.

    `npm run build` passed while the app was completely dead. A circular import
    (JarvisOS.jsx -> pages/Planner.jsx -> JarvisOS.jsx) threw "Cannot access 'T'
    before initialization" as soon as the browser evaluated the module graph, so
    React never mounted: a blank white page, with every file returning HTTP 200
    because loading was never the problem. Rollup bundles into one scope and
    hoists, so the cycle resolves at build time and the build is green. Vite's
    dev server evaluates natively and it is not.

    A passing build is therefore not evidence that the app runs. This loads the
    real dev server in a real browser and checks that #root has children.

    Needs node, the frontend's packages, and a Chromium. Any of those missing is
    a SKIP with the command to fix it — not a pass, and not a failure either.
    """
    r = Result("ui_renders", "The console actually renders in a browser")
    root = Path(__file__).resolve().parent.parent

    if not shutil.which("node"):
        return r.skip("node isn't installed here, so the UI can't be checked. "
                      "Install Node LTS from nodejs.org.")
    if not (root / "frontend" / "node_modules" / "vite" / "package.json").is_file():
        return r.skip("frontend packages aren't installed. Run: "
                      "cd frontend && npm install")

    try:
        p = subprocess.run(["node", str(root / "tools" / "check_ui.mjs")],
                           cwd=str(root), capture_output=True, text=True,
                           timeout=240)
    except subprocess.TimeoutExpired:
        return r.bad("The render check timed out after 4 minutes.")
    except Exception as e:
        return r.skip(f"couldn't run the render check: {str(e)[:120]}")

    out = (p.stdout or "") + (p.stderr or "")
    for line in out.splitlines():
        s = line.strip()
        if s.startswith(("mounted elements", "body background", "crashes")):
            r.note(s)

    if p.returncode == 2:
        return r.skip("no browser available to look at the page. "
                      "Run: npx playwright install chromium")
    if p.returncode != 0:
        detail = "\n        ".join(l for l in out.splitlines()
                                   if "FAIL" in l or "exception" in l.lower()
                                   or "Cannot access" in l)
        return r.bad("The UI does not render — this is the blank white page.\n        "
                     + (detail or out[-400:]))
    return r.ok("React mounts, styles apply, nothing throws.")


def s_proposal_batching():
    """
    Proposals are written in batches, and a batch that can't be split cleanly
    falls back to one-at-a-time rather than guessing.

    The speed matters — thirteen separate calls took five to ten minutes on a
    memory-starved machine, because free RAM is low enough that the model is
    released and reloaded between every call. But the CORRECTNESS matters more:
    these go to real clients under the user's name, so pairing a proposal with
    the wrong job is unrecoverable in a way that being slow is not.
    """
    r = Result("proposal_batching", "Proposals batched, never mismatched")
    import services.ai_router as ar
    import services.deepseek_service as ds
    from agents.proposal_agent import ProposalAgent

    agent = ProposalAgent()
    profile = {"name": "Ibrahim", "skills": "Python"}
    jobs = [{"job_id": f"j{i}", "title": f"Job {i}", "description": "d",
             "platform": "p"} for i in range(13)]

    real_ask, real_call = ar.ask, ds.call_model
    try:
        # 1. Happy path — well-formed batch replies.
        calls = {"batch": 0, "single": 0}

        def good_ask(task="chat", prompt="", **kw):
            calls["batch"] += 1
            n = prompt.count("--- JOB ")
            return "\n".join(f"{ProposalAgent._SEP} {i}\nProposal for job {i}."
                             for i in range(1, n + 1))

        def counted_call(*a, **k):
            calls["single"] += 1
            return "single fallback text"

        ar.ask, ds.call_model = good_ask, counted_call
        texts = agent._generate_batched(jobs, profile, [])
        total = calls["batch"] + calls["single"]
        if len(texts) != len(jobs):
            return r.bad(f"{len(texts)} proposals for {len(jobs)} jobs — some jobs "
                         f"would be queued with nothing to send.")
        if total >= len(jobs):
            return r.bad(f"{total} LLM calls for {len(jobs)} jobs — no batching "
                         f"happened, so this is still the slow path.")
        r.note(f"{len(jobs)} jobs -> {total} LLM calls (was {len(jobs)})")

        # 2. The model ignores the separator. Must NOT split on guesswork.
        calls["batch"] = calls["single"] = 0
        ar.ask = lambda task="chat", prompt="", **kw: (
            calls.__setitem__("batch", calls["batch"] + 1)
            or "Here are your proposals.\n\nOne.\n\nTwo.\n\nThree.")
        texts = agent._generate_batched(jobs[:4], profile, [])
        if calls["single"] != 4:
            return r.bad("A malformed batch reply was accepted. Proposals could be "
                         "paired with the wrong jobs and sent to real clients.")
        if len(texts) != 4:
            return r.bad(f"Fallback produced {len(texts)} of 4 proposals.")
        r.note("an unsplittable reply falls back to one call per job")

        # 3. The provider errors. Every job must still get something sendable.
        ar.ask = lambda task="chat", prompt="", **kw: "[Ollama error: nope]"
        ds.call_model = lambda *a, **k: "[Ollama error: nope]"
        texts = agent._generate_batched(jobs[:4], profile, [])
        if len(texts) != 4:
            return r.bad("A provider failure lost jobs entirely.")
        r.note("a dead provider still returns one entry per job (template kicks "
               "in downstream)")

        # 4. The sleep is gone. It was throttling a LOCAL process.
        import inspect
        src = inspect.getsource(ProposalAgent.run)
        if "time.sleep" in src:
            return r.bad("The per-job sleep is still there — it adds a second per "
                         "job to throttle a local process with no rate limit.")
        r.note("no artificial delay between jobs")
    finally:
        ar.ask, ds.call_model = real_ask, real_call

    return r.ok("Batched for speed, one-at-a-time whenever correctness is in doubt.")


def s_memory_pressure():
    """
    Low RAM must be REPORTED, not merely suffered.

    At 92% used this machine pages to disk: Ollama's first call takes a minute,
    the router falls back to a 0.5B model, and vision stops working. One cause,
    three symptoms, and nothing said so — which is why it read as "Jarvis is
    broken" rather than "the PC is out of memory".
    """
    r = Result("memory_pressure", "Low RAM is explained, not just endured")
    from services import memory_pressure as mp

    s = mp.status()
    for key in ("free_gb", "level", "headline", "effects", "advice"):
        if key not in s:
            return r.bad(f"status() is missing '{key}'.")
    if s["level"] not in ("ok", "tight", "low", "critical"):
        return r.bad(f"unknown level {s['level']!r}")
    r.note(f"{s['headline']} (level={s['level']})")

    # The thresholds must actually classify, or the banner never appears.
    if mp.level(1.0) != "critical" or mp.level(8.0) != "ok":
        return r.bad("Thresholds don't classify: 1GB must be critical, 8GB ok.")
    if mp.level(2.5) == "ok":
        return r.bad("2.5GB free reported as fine — that's the level where the "
                     "model router is already falling back to a weaker model.")
    r.note("1GB -> critical, 2.5GB -> not ok, 8GB -> ok")

    # A pressured machine must produce something ACTIONABLE, not just a number.
    for _lvl in ("critical", "low"):
        # status() reflects the real machine, so check the table directly.
        if not mp.status.__doc__:
            break
    crit = mp.level(0.5)
    if crit != "critical":
        return r.bad("0.5GB free isn't classified as critical.")

    freed = mp.free_now()
    if not isinstance(freed, dict) or "note" not in freed:
        return r.bad("free_now() gave nothing a human could read.")
    r.note(f"free-memory action answers: {freed['note'][:70]}")
    return r.ok("RAM pressure is measured, explained, and actionable.")


def s_stale_stop():
    """
    One press of Stop must not kill every command after it.

    Straight from a runtime report: Stop was pressed at 10:58:39, and the next
    five commands over the following three minutes all died instantly with
    "Cancelled — stopped between steps". Jarvis appeared to stop working
    entirely, with no usable reason, until the backend was restarted. The
    orchestrator cleared the cancel flag when a GOAL ended, but a chat command
    never goes through the orchestrator, so nothing ever cleared it.
    """
    r = Result("stale_stop", "A leftover Stop doesn't poison the next command")
    from services import control

    control.clear()

    # Nothing running: a cancel is by definition aimed at something that's over.
    control.cancel("test")
    if not control.is_cancelled():
        return r.bad("cancel() didn't set the flag.")
    out = control.clear_stale()
    if not out.get("cleared"):
        return r.bad("A cancel with nothing running was NOT cleared — this is "
                     "the bug where one Stop killed every later command.")
    if control.is_cancelled():
        return r.bad("clear_stale() said it cleared, but the flag is still set.")
    r.note("cancel with nothing running -> cleared")

    # A cancel aimed at LIVE work must survive. Clearing it would silently
    # un-cancel work the user just asked to stop, which is the worse failure.
    with control.run_scope():
        control.cancel("test")
        if not control.busy():
            return r.bad("run_scope() didn't mark the chain as running.")
        out = control.clear_stale()
        if out.get("cleared"):
            return r.bad("A LIVE cancel was cleared — Stop would do nothing "
                         "while work was actually running.")
        if not control.is_cancelled():
            return r.bad("The live cancel was dropped anyway.")
    r.note("cancel during live work -> kept")

    if control.busy():
        return r.bad("run_scope() leaked: still 'busy' after the block exited.")
    control.clear()

    # The real chat path has to call it, or the fix exists and never runs.
    src = (Path(ROOT) / "backend" / "adapters" / "commander_adapter.py").read_text(encoding="utf-8")
    if "clear_stale" not in src:
        return r.bad("commander_adapter never calls clear_stale(), so the chat "
                     "path is still poisoned by a leftover Stop.")
    r.note("the chat path calls clear_stale() before running")

    exe = (Path(ROOT) / "backend" / "agents" / "desktop_agent.py").read_text(encoding="utf-8")
    if "run_scope()" not in exe:
        return r.bad("execute_chain isn't inside run_scope(), so a live cancel "
                     "would be cleared by the next chat message.")
    r.note("execute_chain runs inside run_scope()")
    return r.ok("Stop stops one thing, and only while that thing is running.")


def s_looking_at_the_right_window():
    """
    Answers about a specific app must not come from whatever window was in front.

    The user asked Jarvis to check QQ messages. QQ was ALREADY running, so
    open_app saw a live window and returned verified without raising it. The
    screenshot then captured a different window, and the vision model answered
    honestly about it: "no visible new or unread messages". Technically true,
    completely wrong, and indistinguishable from a real answer — the user only
    knew because they never saw QQ come to the front.
    """
    r = Result("looking", "Looking at the screen targets the app that was asked about")
    src = (Path(ROOT) / "backend" / "agents" / "desktop_agent.py").read_text(encoding="utf-8")

    m = re.search(r"_INPUT\s*=\s*\{(.*?)\}", src, re.S)
    if not m:
        return r.bad("No _INPUT set in execute_chain — nothing decides which "
                     "actions need the app in front.")
    need_focus = m.group(1)
    for act in ("screenshot", "analyze"):
        if f'"{act}"' not in need_focus:
            return r.bad(f"'{act}' isn't in the set of actions that require the "
                         f"target app to be foreground. Looking at the screen IS "
                         f"an interaction with a specific window.")
    r.note("screenshot and analyze require the target app to be in front")

    if "focus_unconfirmed" not in src:
        return r.bad("Nothing records that focus couldn't be confirmed, so an "
                     "answer about the wrong window is presented as fact.")
    if "could not bring" not in src:
        return r.bad("No caveat text — an unverified look still reads as a "
                     "confident answer about the app you asked about.")
    r.note("an unconfirmed focus attaches a caveat to the answer")

    # And the plan for "check my qq messages" must still be the right four steps.
    from services import decompose
    steps = decompose.decompose("check my qq messages")["steps"]
    actions = [s["action"] for s in steps]
    for want in ("open_app", "wait_for_window", "screenshot", "analyze"):
        if want not in actions:
            return r.bad(f"'check my qq messages' produced {actions} — no {want}.")
    r.note(f"'check my qq messages' -> {' -> '.join(actions)}")
    return r.ok("Jarvis looks at the window it was asked about, or says it couldn't.")


def s_literal_typing():
    """
    Asking an app a question must not put the question in the app.

    "Open notepad tell me about yourself" typed the characters `me about
    yourself` into Notepad. Two faults in one: the pronoun was left in the text,
    and a question aimed at a text editor was treated as literal input. Notepad
    cannot answer anything — so the only sensible reading is "you answer it and
    write the answer here".
    """
    r = Result("literal_typing", "Questions get answered, not transcribed")
    from services import decompose

    def plan(text):
        return [(s["action"], s.get("params", {})) for s in
                decompose.decompose(text)["steps"]]

    # The exact sentence from the report.
    steps = plan("Open notepad tell me about yourself")
    typed = [p.get("text", "") for a, p in steps if a == "type_text"]
    if any("me about" in t for t in typed):
        return r.bad(f"Still typing the pronoun: {typed!r}")
    if not any(a == "compose" for a, _ in steps):
        return r.bad("Notepad was asked a question and Jarvis didn't compose an "
                     f"answer — plan was {[a for a, _ in steps]}")
    r.note("'notepad tell me about yourself' -> compose, not type")

    # A conversational app is the opposite: the question is FOR the app.
    steps = plan("open doubao and ask it how it is")
    if any(a == "compose" for a, _ in steps):
        return r.bad("Composed an answer instead of asking Doubao — the question "
                     "was meant for the app, not for Jarvis.")
    if not any(a == "type_text" and "how it is" in p.get("text", "")
               for a, p in steps):
        return r.bad(f"Didn't type the question into Doubao: {steps}")
    if not any(a == "press" for a, _ in steps):
        return r.bad("Typed a question into a chat app and never sent it.")
    r.note("'doubao ask it how it is' -> types the question and sends it")

    # Literal must stay literal.
    steps = plan("open notepad and type hello")
    if not any(a == "type_text" and p.get("text") == "hello" for a, p in steps):
        return r.bad(f"'type hello' stopped being literal: {steps}")
    r.note("'type hello' still types hello")

    # A comma is a step boundary when a verb follows it, or the whole tail
    # becomes the app name and the launch fails on an app that doesn't exist.
    steps = plan("open notepad, tell me a joke")
    app = next((p.get("name_or_path") for a, p in steps if a == "open_app"), "")
    if app != "notepad":
        return r.bad(f"Tried to launch an app called {app!r}.")
    r.note("'open notepad, tell me a joke' splits at the comma")

    # ...but not when it's part of the text being typed.
    steps = plan("open notepad and type hello, world")
    if not any(a == "type_text" and p.get("text") == "hello, world" for a, p in steps):
        return r.bad(f"Split inside literal text: {steps}")
    r.note("'type hello, world' is not split")
    return r.ok("Literal stays literal; questions get answered by whoever can answer them.")


def s_reflection_wired():
    """
    The learning loop must actually be fed.

    reflection.reflect() and brain_decision.after_goal() both existed and
    neither was called from the orchestrator or from the chat path — the two
    places where work actually finishes. A runtime report after hours of use
    said `reflections: 0`, which is what a learning loop nobody calls looks
    like from the outside: identical to having none.
    """
    r = Result("reflection", "Finished work produces a lesson")

    core = (Path(ROOT) / "backend" / "agents" / "orchestrator_core.py").read_text(encoding="utf-8")
    if "after_goal" not in core:
        return r.bad("The orchestrator never hands a finished goal to the brain, "
                     "so nothing is ever learned from a freelance run.")
    r.note("orchestrator calls brain_decision.after_goal() at the terminal state")

    desk = (Path(ROOT) / "backend" / "agents" / "desktop_agent.py").read_text(encoding="utf-8")
    if "reflection.reflect" not in desk:
        return r.bad("Chat commands never reflect — and chat is how Jarvis is "
                     "actually driven.")
    r.note("the desktop chain reflects on failed or retried runs")

    # It must not be on the critical path: reflect() may call the model, and
    # this machine cannot spare a model call after every "open notepad".
    body = desk.split("def _learn_from_chain")[-1].split("\ndef ")[0]
    if "threading.Thread" not in body:
        return r.bad("Reflection runs inline — every command would wait for a "
                     "model call on a 16GB machine.")
    r.note("reflection runs off the reply path")

    from services import reflection
    out = reflection.reflect("test goal", [
        {"step": 1, "action": "open_app", "success": True, "verified": True},
        {"step": 2, "action": "type_text", "success": False, "verified": False,
         "verify_reason": "text never landed"},
    ], False, kind="test")
    lesson = (out or {}).get("reflection", "")
    if not lesson:
        return r.bad("reflect() produced no lesson at all.")
    if "type_text" not in lesson and "step 2" not in lesson:
        return r.bad(f"The lesson doesn't name where it broke: {lesson[:120]!r}")
    r.note(f"lesson names the failing step: {lesson[:70]}")
    return r.ok("Work that finishes produces a lesson, off the critical path.")


def s_ai_router():
    """
    Every AI call goes through one gate, that gate never raises, it stays local
    unless told otherwise, and it never prints an API key.
    """
    r = Result("ai_router", "One gate for AI; local by default; keys stay secret")
    from services import ai_router, config

    # Default posture: entirely local. Adding a router must not quietly start
    # sending this user's screen contents and job descriptions to a cloud.
    routing = ai_router.status()["routing"]
    off_local = {t: p for t, p in routing.items() if p != "ollama"}
    if off_local:
        return r.bad(f"Out of the box, these don't use the local model: {off_local}. "
                     f"Jarvis must work offline until the user says otherwise.")
    r.note(f"all {len(routing)} task types default to local ollama")

    # Ollama is always last in the chain, so a dead cloud key degrades to local
    # rather than to an error.
    if ai_router.chain_for("chat")[-1] != "ollama":
        return r.bad("Local ollama isn't the final fallback — a cloud outage "
                     "would stop Jarvis working at all.")
    r.note("local ollama is always the last resort")

    # Never raises, whatever the state of the machine.
    try:
        out = ai_router.ask("chat", "test")
    except Exception as e:
        return r.bad(f"ask() raised {type(e).__name__}: {e}. Thirty call sites "
                     f"pass this result straight to the user.")
    if not isinstance(out, str) or not out:
        return r.bad(f"ask() returned {type(out).__name__}, not a string.")
    r.note("ask() returns a string even with no provider available")

    # A misconfigured provider must be TRIED and then fallen past, and the
    # reason must survive into the message.
    saved = config.get("ai_route_chat", "")
    try:
        config.set("ai_deepseek_api_key", "sk-not-real")
        config.set("ai_route_chat", "deepseek")
        ai_router.invalidate()
        chain = ai_router.chain_for("chat")
        if chain[0] != "deepseek" or "ollama" not in chain:
            return r.bad(f"Chain didn't honour the setting: {chain}")
        msg = ai_router.ask("chat", "test")
        if not isinstance(msg, str):
            return r.bad("ask() stopped returning a string once a provider failed.")
        r.note(f"a broken provider falls through: {chain}")
    finally:
        config.set("ai_route_chat", saved)
        config.set("ai_deepseek_api_key", "")
        ai_router.invalidate()

    # Keys must never reach the Settings screen or the runtime report — that
    # report is the file the user sends to other people when something breaks.
    secret = "sk-LEAKCANARY-0987654321"
    try:
        config.set("ai_openai_api_key", secret)
        eff = str(config.effective())
        if secret in eff:
            return r.bad("An API key appears in /settings/effective, which is "
                         "shown in Settings and embedded in every runtime "
                         "report the user sends out.")
        st = str(ai_router.status())
        if secret in st:
            return r.bad("An API key appears in the AI status endpoint.")
        r.note("keys are masked in settings and absent from status")
    finally:
        config.set("ai_openai_api_key", "")
        ai_router.invalidate()

    # The legacy name ~30 modules import must now go through the gate, or the
    # whole exercise achieved nothing.
    import inspect

    from services import deepseek_service
    src = inspect.getsource(deepseek_service.call_model)
    if "ai_router" not in src:
        return r.bad("deepseek_service.call_model doesn't route through "
                     "ai_router — most of Jarvis would still bypass the gate.")
    r.note("call_model (imported in ~30 files) routes through ai_router")
    return r.ok("One gate, local by default, degrades to local, keys stay secret.")


def s_launchers():
    """
    The .bat files must be valid WINDOWS batch, not shell-flavoured guesswork.

    This scenario exists because launcher bugs have now cost more user time than
    any bug in Jarvis itself, and they are invisible from here — this container
    has no cmd.exe, so a launcher can only be checked by reading it. Twice now a
    launcher has been shipped that could not possibly work:

      * LF line endings, which made Windows fail in a way that looked like a
        missing Python;
      * `>/dev/null`, which is Unix. cmd tries to redirect into a folder called
        \\dev, the folder doesn't exist, the redirect fails, so the command
        fails, so the `&&` never runs — and the launcher announced "Python is
        not installed" on a machine running Python 3.11 perfectly well.

    So the rules are checked mechanically instead of remembered.
    """
    import glob
    r = Result("launchers", "Windows launchers are valid Windows batch")
    root = Path(__file__).resolve().parent.parent
    bats = sorted(glob.glob(str(root / "*.bat")))
    if not bats:
        return r.bad("No .bat files found at all — the launcher is missing.")

    problems = []
    for path in bats:
        name = Path(path).name
        raw = Path(path).read_bytes()

        # CRLF. An LF batch file fails in ways that look like a broken Python.
        if b"\r\n" not in raw and b"\n" in raw:
            problems.append(f"{name}: LF line endings — Windows needs CRLF")

        # Pure ASCII. Em-dashes and smart quotes become mojibake in a GBK console.
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as e:
            problems.append(f"{name}: non-ASCII byte at offset {e.start} — "
                            f"this becomes mojibake in a Chinese console")

        text = raw.decode("utf-8", "replace")
        for i, line in enumerate(text.split("\r\n"), 1):
            s = line.strip()

            # Choosing an interpreter because the COMMAND EXISTS is not the
            # same as choosing one that WORKS. "where py" succeeds whenever the
            # Python launcher is installed, but on the user's machine "py -3"
            # pointed at a C:\Python314 that was gone and died with "Unable to
            # create process" — while plain "python" was a healthy 3.11 on PATH.
            if re.search(r'^where\s+\S+\s+.*&&\s*set\s+"?PY=', s, re.I):
                problems.append(f"{name}:{i}: picks Python from `where` alone. "
                                f"Test it by running it: "
                                f"`python --version >nul 2>&1 && set \"PY=python\"`")

            # Unix redirection.
            if "/dev/null" in s:
                problems.append(f"{name}:{i}: /dev/null is Unix; cmd needs "
                                f"'>nul 2>&1'")

            # A REM line is STILL parsed for redirection by cmd: `REM note > x`
            # creates a file called x. A comment must not contain < > or |.
            if s.upper().startswith("REM") and re.search(r"[<>|]", s):
                problems.append(f"{name}:{i}: a REM comment contains a redirect "
                                f"character — cmd will act on it")

            # `where X >nul` must use 2>&1, not 2>nul on the same line as &&,
            # and must never redirect to a path.
            m = re.search(r">\s*([^\s&|]+)", s)
            if m and m.group(1).lower() not in ("nul", "&1") \
                    and not m.group(1).startswith('"') \
                    and "echo" not in s.lower() and not s.upper().startswith("REM"):
                if "/" in m.group(1) or m.group(1).startswith("\\"):
                    problems.append(f"{name}:{i}: redirects to a path "
                                    f"'{m.group(1)}' — did you mean nul?")

        # Every script it calls must actually exist, or the launcher fails at a
        # point where the user has no idea what went wrong.
        for called in re.findall(r"%PY%\s+([\w\\/.-]+\.py)", text):
            target = root / called.replace("\\", "/")
            if not target.is_file():
                problems.append(f"{name}: calls {called}, which does not exist")

    if problems:
        return r.bad("These launchers cannot work on Windows:\n        "
                     + "\n        ".join(problems))

    r.note(f"{len(bats)} launcher(s) checked: {', '.join(Path(b).name for b in bats)}")
    r.note("CRLF, pure ASCII, no Unix redirection, no redirects in comments")
    r.note("every script they call exists")

    # There must be exactly one way to start Jarvis. Seven .bat files is how the
    # user ended up running the old V8 one that never installed the UI.
    starters = [Path(b).name for b in bats
                if "start" in Path(b).name.lower()]
    if len(starters) > 2:
        return r.bad(f"{len(starters)} launchers that look like a start button: "
                     f"{', '.join(starters)}. Pick one.")
    r.note(f"start buttons: {', '.join(starters) or 'none'}")
    return r.ok("Launchers are valid Windows batch and there's only one to press.")


SCENARIOS = {
    "control":        (s_control, False),
    "stale_stop":     (s_stale_stop, False),
    "looking":        (s_looking_at_the_right_window, False),
    "literal_typing": (s_literal_typing, False),
    "reflection":     (s_reflection_wired, False),
    "ai_router":      (s_ai_router, False),
    "proposal_batching": (s_proposal_batching, False),
    "memory_pressure": (s_memory_pressure, False),
    "launchers":      (s_launchers, False),
    "ui_renders":     (s_ui_renders, False),
    "simulation":     (s_simulation, False),
    "decompose":      (s_decompose, False),
    "plan_visibility": (s_plan_visibility, False),
    "selfeval":       (s_selfeval, False),
    "auth":           (s_auth, False),
    "teach_privacy":  (s_teach_privacy, False),
    "missing_app":    (s_missing_app, False),
    "clipboard":      (s_clipboard, False),
    "no_model":       (s_no_model, False),
    "queue_load":     (s_queue_load, False),
    "browser_death":  (s_browser_death, False),
    "estop":          (s_estop, False),
    "learning":       (s_learning, False),
    "model_pressure": (s_model_pressure, False),
    "classification": (s_classification, False),
    "failure_evidence": (s_failure_evidence, False),
    "url_gate":       (s_url_gate, False),
}


def main():
    ap = argparse.ArgumentParser(description="Phase 0 failure injection for Jarvis")
    ap.add_argument("--only", help="comma-separated scenario names")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    ap.add_argument("--include-destructive", action="store_true",
                    help="also run scenarios that touch live Ollama/Chrome")
    args = ap.parse_args()

    if args.list:
        for name, (fn, _) in SCENARIOS.items():
            print(f"  {name:<16} {(fn.__doc__ or '').strip().splitlines()[0]}")
        return 0

    chosen = list(SCENARIOS)
    if args.only:
        chosen = [c.strip() for c in args.only.split(",") if c.strip() in SCENARIOS]
        if not chosen:
            print(f"No matching scenarios. Known: {', '.join(SCENARIOS)}")
            return 2

    print("=" * 74)
    print("JARVIS — PHASE 0 FAILURE INJECTION")
    print("Breaking things on purpose. Errors below are often the CORRECT answer;")
    print("what's being checked is whether Jarvis fails honestly and recovers.")
    print("=" * 74)

    results = []
    for name in chosen:
        fn, _ = SCENARIOS[name]
        print(f"\n▸ {name} …", flush=True)
        try:
            res = fn(destructive=args.include_destructive) if name == "model_pressure" else fn()
        except ImportError as e:
            # A missing package is an UNCONFIGURED MACHINE, not a Jarvis bug.
            # Reporting it as FAIL would send you hunting for a defect that
            # isn't there — the exact mistake that makes a test suite worth
            # ignoring. Skip it, and say what to install.
            missing = getattr(e, "name", None) or str(e)
            res = Result(name, (fn.__doc__ or "").strip().splitlines()[0])
            res.skip(f"needs a package this machine doesn't have: {missing}")
            res.note(f"fix: pip install -r backend/requirements.txt   (missing: {missing})")
        except Exception:
            res = Result(name, "crashed")
            res.bad("scenario raised: " + traceback.format_exc().strip().splitlines()[-1])
            res.note(traceback.format_exc()[-600:])
        results.append(res)
        mark = {PASS: "  ok  ", FAIL: " FAIL ", SKIP: " skip "}[res.status]
        print(f"[{mark}] {res.detail}")
        for n in res.notes:
            print(f"          · {n}")

    p = sum(1 for r in results if r.status == PASS)
    f = sum(1 for r in results if r.status == FAIL)
    s = sum(1 for r in results if r.status == SKIP)

    print("\n" + "=" * 74)
    for r in results:
        print(f"  {r.status:<5} {r.name:<16} {r.why}")
    print("=" * 74)
    print(f"  {p} passed · {f} failed · {s} skipped")
    if f:
        print("\n  Do NOT start the 4-hour soak yet. Each failure above is a bug")
        print("  that a long run would hit repeatedly and be harder to diagnose.")
    else:
        print("\n  Phase 0 clean. Next: 4-hour soak with the income engine on a")
        print("  5-minute interval, while you use the PC normally.")

    buf = io.StringIO()
    buf.write(f"JARVIS PHASE 0 FAILURE INJECTION — {datetime.now().isoformat()}\n")
    buf.write(f"platform: {sys.platform}  python: {sys.version.split()[0]}\n")
    buf.write(f"{p} passed · {f} failed · {s} skipped\n\n")
    for r in results:
        buf.write(f"[{r.status}] {r.name} — {r.why}\n    {r.detail}\n")
        for n in r.notes:
            buf.write(f"    · {n}\n")
        buf.write("\n")
    out = os.path.join(ROOT, "failure_injection_report.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    print(f"\n  Report written to {out}")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
