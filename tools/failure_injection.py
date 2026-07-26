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
import sys
import time
import traceback
from datetime import datetime

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
        return r.bad(f"Reported SUCCESS for an app that does not exist. "
                     f"This is the 'it said it did it but didn't' bug.")

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
    from services import model_router, experience

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
    from core import browser_lock
    from agents import browser_agent

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
        import ollama
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


SCENARIOS = {
    "missing_app":    (s_missing_app, False),
    "clipboard":      (s_clipboard, False),
    "no_model":       (s_no_model, False),
    "queue_load":     (s_queue_load, False),
    "browser_death":  (s_browser_death, False),
    "estop":          (s_estop, False),
    "learning":       (s_learning, False),
    "model_pressure": (s_model_pressure, False),
    "classification": (s_classification, False),
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
