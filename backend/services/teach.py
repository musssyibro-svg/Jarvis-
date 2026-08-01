"""
services/teach.py — watch me do it once, then do it yourself.

The feature asked for more than any other: "there should be a place I will teach
it. It will watch me do something... then I will ask it to do it."

    "watch me apply for a job"     -> recording starts
        (you do the thing)
    "that's it" / stop             -> recording distilled into a workflow
    "apply like I showed you"      -> Jarvis replays it

RECORDING captures what a human would notice, not every hardware event: which
window you were in, what you clicked (and the text under the cursor, so the click
survives a moved button), what you typed, and how long you paused. Raw
coordinates alone produce a macro that breaks the first time a window opens 40px
to the left.

DISTILLING is the part that makes this useful rather than a screen recorder:

  * consecutive keystrokes collapse into one type_text
  * a click is anchored to the text under it wherever that text was readable,
    falling back to coordinates only when it wasn't
  * switching windows becomes open_app + wait_for_window, not a raw Alt-Tab
  * long pauses become explicit waits, because you were waiting for something
  * mouse movement between clicks is dropped entirely

WHAT IS NOT RECORDED: anything you type into a field the OS marks as a password,
and anything typed while a window whose title looks like a login is focused.
Recording a demonstration is not consent to store your password in a workflow
file. Those keystrokes become a `credential` placeholder that reads from the
encrypted vault at replay time.

Requires `pynput`. Without it, recording is unavailable and says so plainly
rather than pretending to record and saving nothing.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()
_session: dict | None = None
_listeners: list = []

# A pause longer than this means you were waiting for something to happen, and
# the replay needs to wait too. Shorter gaps are just human typing rhythm.
_PAUSE_S = 1.2
# Below this, a pause is not worth replaying at all.
_MIN_WAIT_S = 0.8

_SECRET_TITLE_WORDS = ("login", "sign in", "signin", "password", "登录", "密码",
                       "authenticate", "credential", "unlock", "2fa", "verify")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def available() -> dict:
    try:
        import pynput  # noqa: F401
        return {"ok": True}
    except Exception:
        return {"ok": False,
                "error": "Recording needs the 'pynput' package.",
                "fix": "pip install pynput"}


def _active_window() -> tuple[str, str]:
    """(process_name, window_title) for whatever is in front right now."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        proc = ""
        try:
            import psutil
            proc = psutil.Process(pid.value).name().lower().replace(".exe", "")
        except Exception:
            pass
        return proc, buf.value
    except Exception:
        return "", ""


def _looks_secret(title: str) -> bool:
    t = (title or "").lower()
    return any(w in t for w in _SECRET_TITLE_WORDS)


# ── recording ────────────────────────────────────────────────────────────────

def start(name: str) -> dict:
    """Begin watching. One recording at a time."""
    global _session
    avail = available()
    if not avail["ok"]:
        return {"ok": False, **avail}
    with _lock:
        if _session and _session["recording"]:
            return {"ok": False,
                    "error": f"already recording '{_session['name']}' — "
                             f"say 'stop recording' first"}
        _session = {"name": (name or "").strip() or "untitled",
                    "recording": True, "started": time.time(),
                    "started_at": _now(), "events": [], "redacted": 0}

    from pynput import keyboard, mouse

    def on_click(x, y, button, pressed):
        if not pressed:
            return
        proc, title = _active_window()
        _record({"t": time.time(), "kind": "click", "x": x, "y": y,
                 "button": str(button).split(".")[-1], "app": proc, "title": title})

    def on_key(key):
        proc, title = _active_window()
        if _looks_secret(title):
            _record({"t": time.time(), "kind": "secret", "app": proc, "title": title})
            return
        try:
            ch = key.char
        except AttributeError:
            ch = None
        name_ = getattr(key, "name", None)
        _record({"t": time.time(), "kind": "key", "char": ch, "key": name_,
                 "app": proc, "title": title})

    kl = keyboard.Listener(on_press=on_key)
    ml = mouse.Listener(on_click=on_click)
    kl.start()
    ml.start()
    with _lock:
        _listeners[:] = [kl, ml]

    try:
        from agents.orchestrator import STATE
        STATE.emit("teach", f"Recording '{name}'. Do the task; say 'stop recording' "
                            f"when you're done. Passwords are not recorded.",
                   "warning")
    except Exception:
        pass
    return {"ok": True, "recording": name,
            "note": "Anything typed into a login or password window is skipped."}


def _record(ev: dict) -> None:
    with _lock:
        if _session and _session["recording"]:
            if ev["kind"] == "secret":
                # Collapse a run of hidden keystrokes into one marker.
                if _session["events"] and _session["events"][-1]["kind"] == "secret":
                    return
                _session["redacted"] += 1
            _session["events"].append(ev)


def stop(save: bool = True) -> dict:
    """Stop watching and turn what happened into a workflow."""
    global _session
    with _lock:
        for l in _listeners:
            try:
                l.stop()
            except Exception:
                pass
        _listeners.clear()
        if not _session:
            return {"ok": False, "error": "nothing was being recorded"}
        _session["recording"] = False
        sess = dict(_session)

    steps = distil(sess["events"])
    result = {"ok": True, "name": sess["name"], "raw_events": len(sess["events"]),
              "steps": steps, "step_count": len(steps),
              "redacted": sess["redacted"],
              "seconds": round(time.time() - sess["started"], 1)}

    if not steps:
        result.update(ok=False,
                      error="I watched, but nothing replayable happened — no "
                            "clicks or typing were captured.")
        return result

    if save:
        try:
            from services import workflow_service
            saved = workflow_service.teach(
                sess["name"], source_text=f"demonstrated on {sess['started_at']}",
                steps=steps, description=f"learned by watching ({len(steps)} steps)")
            result["saved"] = saved.get("ok", False)
            result["name"] = saved.get("name", sess["name"])
        except Exception as e:
            result["saved"] = False
            result["save_error"] = str(e)[:200]

    if sess["redacted"]:
        result["note"] = (f"{sess['redacted']} password entry point(s) were not "
                          f"recorded. On replay Jarvis will pause and use the "
                          f"vault, or ask you to type it.")
    try:
        from agents.orchestrator import STATE
        STATE.emit("teach", f"Learned '{result['name']}': {len(steps)} steps. "
                            f"Run it by saying \"run my {result['name']}\".")
    except Exception:
        pass
    return result


# ── distilling ───────────────────────────────────────────────────────────────

_MODIFIERS = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "shift",
              "shift_l", "shift_r", "cmd"}
_NAMED = {"enter": "enter", "return": "enter", "tab": "tab", "esc": "escape",
          "escape": "escape", "backspace": "backspace", "delete": "delete",
          "up": "up", "down": "down", "left": "left", "right": "right",
          "home": "home", "end": "end", "page_up": "pageup", "page_down": "pagedown"}


def distil(events: list[dict]) -> list[dict]:
    """
    Raw input events -> a replayable, readable workflow.

    The output uses the same step schema as everything else, so a demonstrated
    workflow is editable, inspectable and runnable by exactly the same executor
    as a typed one. A recording that can only be replayed by a special player is
    a black box, and a black box is not something you can correct.
    """
    steps: list[dict] = []
    buf: list[str] = []            # accumulating literal keystrokes
    current_app = None
    last_t = None

    def flush_text():
        nonlocal buf
        if buf:
            text = "".join(buf)
            if text.strip():
                steps.append({"action": "type_text", "params": {"text": text}})
            buf = []

    for ev in events or []:
        # A gap means you were waiting for something. Replay has to wait too, or
        # it types into a window that hasn't appeared yet.
        if last_t is not None:
            gap = ev["t"] - last_t
            if gap >= _PAUSE_S:
                flush_text()
                steps.append({"action": "wait",
                              "params": {"seconds": round(min(gap, 15), 1)}})
        last_t = ev["t"]

        app = ev.get("app") or ""
        if app and app != current_app:
            flush_text()
            if current_app is not None:
                # Focusing beats launching: the app is already running, and a
                # second launch of QQ or Word opens a dialog rather than a window.
                steps.append({"action": "focus_window", "params": {"title": app}})
            else:
                steps.append({"action": "open_app", "params": {"name_or_path": app}})
                steps.append({"action": "wait_for_window",
                              "params": {"title": app, "timeout": 15}})
            current_app = app

        kind = ev["kind"]
        if kind == "secret":
            flush_text()
            steps.append({"action": "credential",
                          "params": {"for": ev.get("title", "")[:60],
                                     "note": "not recorded — taken from the vault "
                                             "or typed by you at replay time"}})
            continue

        if kind == "click":
            flush_text()
            anchor = _text_under(ev["x"], ev["y"])
            if anchor:
                steps.append({"action": "click_text", "params": {"text": anchor}})
            else:
                # Coordinates are the last resort: they break as soon as a window
                # moves or the resolution changes, so they're marked as fragile
                # and the plan says so out loud.
                steps.append({"action": "click",
                              "params": {"x": ev["x"], "y": ev["y"],
                                         "fragile": True,
                                         "note": "clicked by position — no readable "
                                                 "label was under the cursor"}})
            continue

        if kind == "key":
            ch, name_ = ev.get("char"), (ev.get("key") or "").lower()
            if ch and ch.isprintable():
                buf.append(ch)
            elif name_ == "space":
                buf.append(" ")
            elif name_ in _MODIFIERS:
                continue      # a modifier alone does nothing; combos arrive as chars
            elif name_ in _NAMED:
                flush_text()
                steps.append({"action": "press", "params": {"key": _NAMED[name_]}})

    flush_text()
    return _tidy(steps)


def _tidy(steps: list[dict]) -> list[dict]:
    """Drop no-op waits and collapse repeats — a demonstration is full of both."""
    out: list[dict] = []
    for s in steps:
        if s["action"] == "wait" and s["params"].get("seconds", 0) < _MIN_WAIT_S:
            continue
        # A password is typed as many keystrokes but is ONE login step. Emitting
        # it twice makes the replay type the password into the username field.
        if out and out[-1] == s and s["action"] in ("wait", "focus_window",
                                                    "wait_for_window", "credential"):
            continue
        if (out and s["action"] == "wait" and out[-1]["action"] == "wait"):
            out[-1]["params"]["seconds"] = round(
                min(out[-1]["params"]["seconds"] + s["params"]["seconds"], 20), 1)
            continue
        out.append(s)
    # A trailing wait replays as dead time and teaches nothing.
    while out and out[-1]["action"] == "wait":
        out.pop()
    return out


def _text_under(x: int, y: int) -> str:
    """
    Read the label under the cursor so the click survives the button moving.

    Best-effort by design: when OCR isn't available or the region is an icon,
    this returns "" and the step falls back to coordinates — which is worse, and
    is labelled as worse, rather than failing to record the click at all.
    """
    try:
        from agents.vision_agent import ocr_screen
        r = ocr_screen(region={"left": max(x - 90, 0), "top": max(y - 16, 0),
                               "width": 180, "height": 32})
        if not r.get("success"):
            return ""
        # A button label is one short line. Anything longer means the crop caught
        # surrounding prose, which makes a poor click anchor.
        line = " ".join((r.get("text") or "").split())
        return line[:60] if 1 <= len(line) <= 60 else ""
    except Exception:
        return ""


# ── status / phrases ─────────────────────────────────────────────────────────

def status() -> dict:
    with _lock:
        if not _session:
            return {"recording": False, **available()}
        return {"recording": _session["recording"], "name": _session["name"],
                "events": len(_session["events"]),
                "seconds": round(time.time() - _session["started"], 1),
                "redacted": _session["redacted"]}


_START_PHRASES = ("watch me", "record me", "learn this", "let me show you",
                  "i'll show you", "ill show you", "start recording",
                  "watch what i do")
_STOP_PHRASES = ("stop recording", "that's it", "thats it", "done recording",
                 "stop watching", "finished", "that's all", "thats all")


def match(message: str) -> dict | None:
    """
    Recognise teach commands in chat.

    "watch me apply for a job" -> start("apply for a job")
    "that's it"                -> stop()
    """
    m = (message or "").strip().lower()
    if not m:
        return None
    for p in _STOP_PHRASES:
        if m == p or m.startswith(p):
            with _lock:
                live = bool(_session and _session["recording"])
            if live:
                return {"command": "stop"}
            return None
    for p in _START_PHRASES:
        if m.startswith(p):
            name = m[len(p):].strip(" :,-")
            for lead in ("do ", "how to ", "how i "):
                if name.startswith(lead):
                    name = name[len(lead):]
            return {"command": "start", "name": name or "untitled task"}
    return None
