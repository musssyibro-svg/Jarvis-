"""
services/simulate.py — "what would you do?", answered without doing it.

Trust in an autonomous system is not built by watching it succeed. It's built by
being able to check its intentions before it acts. "Apply for jobs" is a
frightening thing to say to something that can submit on your behalf; "here is
what I would do, proceed?" is not.

    Simulation
      would search    remoteok, weworkremotely, hubstaff
      would find      ~15 jobs
      would draft     up to 10 proposals
      would submit    0 (approval is required)
      would take      about 8 minutes
      Proceed?

Two things are simulated:

  TASKS      a desktop/browser command. Reuses decompose(), so the plan shown
             is the EXACT step list that would run — not a description of it.
             Every step is annotated with whether it touches anything real.

  EARNING    a freelance cycle. Reads the live config, the real platform list,
             real platform health and the real queue, then reports what a cycle
             would do. Numbers come from configuration and history, not from
             running a scan.

THE ONE RULE: a simulation must never execute anything. No app opens, no page
loads, no keystroke is sent, no row is written. Everything below is computed
from configuration, history and static resolution. A "dry run" with side effects
is worse than no dry run, because it is trusted.

Estimates are labelled as estimates and derived from measured history where
there is any (experience.py knows how long this machine really takes to open an
app). Where there is no history, it says so rather than inventing a number.
"""
from __future__ import annotations


# ── what a step actually touches ─────────────────────────────────────────────

# Anything that changes something outside Jarvis. These are the lines in a plan
# worth reading twice before approving.
_SIDE_EFFECTS = {
    "open_app":    ("opens a window on your screen", "visible"),
    "close_app":   ("closes a running program", "disruptive"),
    "open_url":    ("loads a web page", "network"),
    "type_text":   ("types into whatever has focus", "writes"),
    "compose":     ("generates text, then types it", "writes"),
    "press":       ("sends a keystroke", "writes"),
    "hotkey":      ("sends a key combination", "writes"),
    "click":       ("clicks at a screen position", "writes"),
    "click_text":  ("clicks on something on screen", "writes"),
    "scroll":      ("scrolls the active window", "visible"),
    "credential":  ("fills a saved login", "sensitive"),
    "write_file":  ("writes a file to disk", "writes"),
    "run_command": ("runs a shell command", "sensitive"),
}
_HARMLESS = {"screenshot", "analyze", "wait", "wait_for_window", "focus_window"}


def _estimate(step: dict) -> tuple[float, str]:
    """
    How long would this step take, and do we actually know?

    Measured history beats a guess, and the difference is stated. A confident
    fabricated number is worse than an honest "no idea yet" — it gets used for
    planning and then quietly disappoints.
    """
    action = (step or {}).get("action", "")
    params = (step or {}).get("params", {}) or {}

    if action == "wait":
        return float(params.get("seconds", 2)), "exact"

    if action in ("open_app", "wait_for_window"):
        target = params.get("name_or_path") or params.get("title") or ""
        try:
            from services import experience
            got = experience.launch_wait_for(target)
            if got.get("samples", 0) >= 3:
                return float(got.get("seconds", 4)), "measured here"
        except Exception:
            pass
        return 4.0, "typical"

    if action == "analyze":
        # Vision on a CPU is the slowest thing Jarvis does. Saying "2s" here
        # would make every estimate a lie on this particular machine.
        try:
            from services import environment
            if not environment.get("gpu.usable_for_llm"):
                return 45.0, "no GPU — vision runs on the CPU"
        except Exception:
            pass
        return 12.0, "typical"

    if action == "compose":
        return 15.0, "typical"
    if action in ("type_text",):
        text = str(params.get("text", ""))
        try:
            from services import config
            per_char = float(config.get("typing_speed", "0.03") or 0.03)
        except Exception:
            per_char = 0.03
        return max(len(text) * per_char, 0.5), "from your typing speed"
    if action == "open_url":
        return 3.0, "typical"
    return 1.0, "typical"


def task(command: str) -> dict:
    """
    Dry-run a command. Nothing is executed.

    Returns the exact steps that would run, what each one touches, a time
    estimate with its basis, and anything that would stop it.
    """
    from services import decompose

    d = decompose.decompose(command or "")
    if not d.get("ok"):
        return {"kind": "task", "command": command, "possible": False,
                "reason": d.get("reason") or "I don't know how to do that yet",
                "unresolved": d.get("unresolved", []),
                "would": [], "seconds": 0}

    would, total = [], 0.0
    for i, step in enumerate(d["steps"]):
        action = step.get("action", "")
        secs, basis = _estimate(step)
        total += secs
        effect, level = _SIDE_EFFECTS.get(
            action, ("reads only, changes nothing", "safe")
            if action in _HARMLESS else ("unknown effect", "unknown"))
        would.append({
            "n": i + 1,
            "text": decompose.describe(step),
            "action": action,
            "effect": effect,
            "level": level,
            "seconds": round(secs, 1),
            "basis": basis,
        })

    blockers = _blockers(d["steps"])
    return {
        "kind": "task",
        "command": command,
        "possible": not any(b["fatal"] for b in blockers),
        "would": would,
        "seconds": round(total, 1),
        "estimate": _human_time(total),
        "changes_things": [w for w in would if w["level"] != "safe"],
        "blockers": blockers,
        "unresolved": d.get("unresolved", []),
        "note": "Nothing was run. No window opened, nothing was typed.",
    }


def _blockers(steps: list[dict]) -> list[dict]:
    """
    What would stop this, checked WITHOUT starting anything.

    Resolution only: is the app known, is a model present, is there a browser.
    Deliberately does not "test" by launching — a simulation that opens a window
    to check whether it can open a window is not a simulation.
    """
    out = []
    try:
        from services import environment
        env = environment.scan()
    except Exception:
        env = {}

    needs_model = any(s.get("action") in ("compose", "analyze") for s in steps)
    if needs_model and not env.get("ollama", {}).get("running"):
        out.append({"fatal": True, "what": "Ollama isn't running",
                    "why": "steps that write or read the screen need a local model",
                    "fix": "start Ollama, then simulate again"})

    for s in steps:
        if s.get("action") != "open_app":
            continue
        name = (s.get("params") or {}).get("name_or_path", "")
        if not name:
            continue
        try:
            from services import app_resolver
            found = app_resolver.resolve(name)
        except Exception:
            found = None
        if not found and name not in (env.get("apps") or {}) \
                and name not in (env.get("browsers") or {}):
            out.append({"fatal": False, "what": f"'{name}' hasn't been located yet",
                        "why": "it may still be found via the Start Menu at run time",
                        "fix": f"open {name} by hand once and Jarvis will remember "
                               f"where it lives"})

    if any(s.get("action") == "credential" for s in steps):
        out.append({"fatal": False, "what": "this needs a saved login",
                    "why": "a demonstration recorded a password field here",
                    "fix": "add it under Settings -> Logins, or be ready to type it"})
    return out


def _human_time(seconds: float) -> str:
    if seconds < 60:
        return f"about {int(seconds)} seconds"
    if seconds < 3600:
        return f"about {int(seconds / 60)} minute{'s' if seconds >= 120 else ''}"
    return f"about {seconds / 3600:.1f} hours"


# ── the freelance engine ─────────────────────────────────────────────────────

def earning() -> dict:
    """
    What one freelance cycle would do, without scanning or submitting anything.

    This is the one people most want before pressing the button: the engine can
    submit real proposals to real clients under your name, and "trust me" is not
    an acceptable answer to "what are you about to do?".
    """
    try:
        from services import income_engine
        cfg = income_engine.get_config()
        status = income_engine.status()
    except Exception as e:
        return {"kind": "earning", "possible": False, "reason": str(e)[:200]}

    try:
        platforms = income_engine._active_platforms(cfg)
    except Exception:
        platforms = cfg.get("platforms") or []

    try:
        from services import config
        max_jobs = int(config.get("income_max_jobs", "15") or 15)
        min_score = int(config.get("income_min_score", "30") or 30)
        auto = (config.get("auto_submit", "false") or "false").lower() in ("1", "true", "yes")
    except Exception:
        max_jobs, min_score, auto = 15, 30, False

    try:
        from services import profile_service
        prof = profile_service.get_profile()
        max_generate = int(prof.get("max_generate") or 10)
    except Exception:
        prof, max_generate = {}, 10

    # Real queue state, read not computed.
    pending = approved = 0
    try:
        from models.db import conn
        with conn() as db:
            rows = db.execute("SELECT status, COUNT(*) n FROM automation_queue "
                              "GROUP BY status").fetchall()
        counts = {r["status"]: r["n"] for r in rows}
        pending, approved = counts.get("pending", 0), counts.get("approved", 0)
    except Exception:
        pass

    # Per-site health, so a paused site is shown as paused rather than promised.
    # should_scan() is the same check a real cycle makes, which is the point —
    # a simulation that consults a different source can disagree with reality.
    health = []
    for p in platforms:
        try:
            from services import platform_health
            will_scan, why = platform_health.should_scan(p)
        except Exception:
            will_scan, why = True, ""
        health.append({"platform": p, "paused": not will_scan, "note": why})
    live = [h for h in health if not h["paused"]]

    steps = [
        {"n": 1, "would": f"Search {len(live)} platform(s): "
                          f"{', '.join(h['platform'] for h in live) or 'none available'}",
         "level": "network"},
        {"n": 2, "would": f"Keep jobs scoring {min_score} or better, up to {max_jobs}",
         "level": "safe"},
        {"n": 3, "would": f"Write up to {max_generate} proposals as "
                          f"{prof.get('name') or 'you'}",
         "level": "writes"},
        {"n": 4, "would": ("SUBMIT them automatically — auto-submit is ON"
                           if auto else
                           "Put them in the queue and wait for you to approve"),
         "level": "sensitive" if auto else "safe"},
    ]

    # Roughly: a scan per site, plus a model call per proposal. Vision-free, so
    # the dominant cost is generation.
    est = len(live) * 25 + max_generate * 20
    warnings = []
    if auto:
        warnings.append("Auto-submit is ON. Proposals will be sent to real "
                        "clients without you seeing them first.")
    if not live:
        warnings.append("Every platform is paused or unconfigured — a cycle "
                        "would find nothing.")
    paused = [h for h in health if h["paused"]]
    if paused:
        warnings.append("Paused: " + ", ".join(
            f"{h['platform']} ({h['note'] or 'repeated failures'})" for h in paused))
    if pending:
        warnings.append(f"{pending} proposal(s) are already waiting for you to "
                        f"approve. A new cycle adds to that.")

    return {
        "kind": "earning",
        "possible": bool(live),
        "running": bool(status.get("running")),
        "would": steps,
        "platforms": health,
        "queue": {"pending": pending, "approved": approved},
        "auto_submit": auto,
        "seconds": est,
        "estimate": _human_time(est),
        "warnings": warnings,
        "note": "Nothing was scanned and nothing was sent. These numbers come "
                "from your settings and the current queue.",
    }


def as_text(sim: dict) -> str:
    """The simulation as a block a person can read in chat."""
    if not sim:
        return "Nothing to simulate."
    if sim.get("kind") == "earning":
        lines = ["If you start earning now:", ""]
        for s in sim["would"]:
            mark = "!" if s["level"] in ("sensitive", "writes") else " "
            lines.append(f"  {mark} {s['n']}. {s['would']}")
        lines += ["", f"  Would take: {sim['estimate']} (estimate)"]
        if sim["queue"]["pending"]:
            lines.append(f"  Already waiting for you: {sim['queue']['pending']} draft(s)")
        for w in sim.get("warnings", []):
            lines.append(f"  ! {w}")
        lines += ["", sim["note"], "", "Say \"start earning\" to actually do it."]
        return "\n".join(lines)

    # Not understood at all — there is no plan to show.
    if not sim.get("would"):
        out = [f"I don't know how to do \"{sim.get('command', '')}\""
               + (f" — {sim['reason']}" if sim.get("reason") else ".")]
        for u in sim.get("unresolved", []):
            out.append(f"  The part I don't understand: \"{u}\"")
        for b in sim.get("blockers", []):
            out.append(f"  - {b['what']}: {b['fix']}")
        return "\n".join(out)

    # Understood but currently blocked. Still show the plan: knowing WHAT it
    # would do is the point, and "it's blocked" without the plan tells you
    # nothing about whether you'd have wanted it in the first place.
    head = (f"If you ask me to \"{sim['command']}\", here's exactly what happens:"
            if sim.get("possible") else
            f"This is what \"{sim['command']}\" would do — but it can't run right "
            f"now (see the bottom):")
    lines = [head, ""]
    for s in sim["would"]:
        mark = "!" if s["level"] not in ("safe",) else " "
        lines.append(f"  {mark} {s['n']}. {s['text']}")
        lines.append(f"        {s['effect']} · ~{s['seconds']}s ({s['basis']})")
    lines += ["", f"  Total: {sim['estimate']}"]
    changing = sim.get("changes_things") or []
    if changing:
        lines.append(f"  {len(changing)} of {len(sim['would'])} steps change "
                     f"something outside Jarvis.")
    for b in sim.get("blockers", []):
        lines.append(f"  {'STOPS IT' if b['fatal'] else 'heads up'}: {b['what']} "
                     f"— {b['fix']}")
    for u in sim.get("unresolved", []):
        lines.append(f"  I don't understand this part: \"{u}\"")
    lines += ["", sim["note"]]
    return "\n".join(lines)


# ── recognising the request ──────────────────────────────────────────────────

_PREFIXES = (
    "simulate ", "dry run ", "dry-run ", "what would you do if ",
    "what would happen if ", "preview ", "pretend ", "rehearse ",
    "what would you do when i say ", "don't do it but ",
)
# Stems, not phrases. "simulate applying for jobs" and "simulate apply for jobs"
# are the same request, and matching only the exact phrase sent one of them down
# the desktop-task path where it became a nonsense plan.
_EARNING_WORDS = ("earn", "freelanc", "job", "proposal", "bid", "income",
                  "appl", "client", "gig")


def match(message: str) -> dict | None:
    """
    Is this a "show me first" request?

    Only fires on an explicit prefix. Guessing that a normal command was meant
    as a simulation would mean the thing the user asked for silently doesn't
    happen, which is worse than doing it.
    """
    m = (message or "").strip().lower()
    if not m:
        return None
    for p in _PREFIXES:
        if m.startswith(p):
            rest = m[len(p):].strip(" :,?\"'")
            # "what would you do if I SAY open notepad" — the command starts
            # after the quoting phrase. Leaving it in makes the first clause
            # "i say open notepad", which parses as an app called "i say".
            for lead in ("i say ", "i said ", "you say ", "i ask you to ",
                         "i tell you to ", "i asked you to ", "i type "):
                if rest.startswith(lead):
                    rest = rest[len(lead):].strip()
                    break
            if not rest or any(w in rest for w in _EARNING_WORDS):
                return {"what": "earning"}
            return {"what": "task", "command": rest}
    if m in ("what would you do", "simulate", "dry run", "show me first"):
        return {"what": "earning"}
    return None
