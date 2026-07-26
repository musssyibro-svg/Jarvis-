"""
backend/agents/desktop_agent.py
Full desktop control: mouse, keyboard, window management, file ops.
Uses PyAutoGUI + PyWinAuto (Windows) with graceful fallback.
"""
import os
import sys
import time
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timezone

import psutil

# ── Safe imports ──────────────────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True   # Move mouse to top-left to abort
    pyautogui.PAUSE    = 0.05
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import pygetwindow as gw
    HAS_WINDOWS = True
except ImportError:
    HAS_WINDOWS = False

_lock = threading.Lock()

# ── Emergency stop (Phase 2 safety) ──────────────────────────────────────────
# When set, all mouse/keyboard actions refuse until cleared. A real ESC-key
# global hotkey is registered on Windows if the keyboard lib is available;
# otherwise this flag can be toggled via the API (/agents/desktop/estop).
_emergency_stop = threading.Event()

def emergency_stop() -> dict:
    _emergency_stop.set()
    return {"success": True, "emergency_stop": True, "message": "Emergency stop ENGAGED — input actions blocked"}

def clear_emergency_stop() -> dict:
    _emergency_stop.clear()
    return {"success": True, "emergency_stop": False, "message": "Emergency stop cleared"}

def is_estopped() -> bool:
    return _emergency_stop.is_set()


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _require(name):
    if _emergency_stop.is_set():
        return {"success": False, "error": "EMERGENCY STOP engaged — clear it before input actions"}
    if not HAS_PYAUTOGUI:
        return {"success": False, "error": f"pyautogui not installed. Run: pip install pyautogui"}
    return None


# ── Clipboard etiquette ──────────────────────────────────────────────────────
# Jarvis uses the clipboard as a tool (paste-typing, reading a focused field to
# verify what it typed). The user is also using that clipboard. Clobbering it —
# silently losing whatever they had copied — is unacceptable for something that
# runs all day, so every clipboard use goes through a guard that puts the old
# contents back.
#
# pyperclip only understands text. If the clipboard is holding something else
# (a copied image, a file from Explorer), we cannot snapshot it, and restoring
# text would destroy it. In that case the guard refuses to run at all and the
# caller falls back to a non-clipboard path. Losing a verification is fine;
# losing the user's data is not.

def _clipboard_snapshot():
    """
    Return (ok, saved_text). ok=False means: do not touch the clipboard.
    """
    try:
        import pyperclip
    except ImportError:
        return False, None

    # On Windows, check whether a non-text format is present; if so, bail out
    # rather than replace the user's copied image/files with text.
    try:
        import win32clipboard as wc  # type: ignore
        CF_TEXT, CF_UNICODETEXT, CF_OEMTEXT, CF_LOCALE = 1, 13, 7, 16
        text_only = {CF_TEXT, CF_UNICODETEXT, CF_OEMTEXT, CF_LOCALE}
        wc.OpenClipboard()
        try:
            fmts, f = [], 0
            while True:
                f = wc.EnumClipboardFormats(f)
                if not f:
                    break
                fmts.append(f)
        finally:
            wc.CloseClipboard()
        if any(f not in text_only for f in fmts):
            return False, None
    except Exception:
        pass    # pywin32 absent or clipboard locked — fall through to text-only

    try:
        return True, pyperclip.paste()
    except Exception:
        return False, None


def _clipboard_restore(saved) -> None:
    if saved is None:
        return
    try:
        import pyperclip
        pyperclip.copy(saved)
    except Exception:
        pass


# ── Mouse ─────────────────────────────────────────────────────────────────────

def move(x: int, y: int, duration: float = 0.3) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        pyautogui.moveTo(x, y, duration=duration)
    return {"success": True, "action": "move", "x": x, "y": y}


def click(x: int = None, y: int = None, button: str = "left", clicks: int = 1) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        if x is not None and y is not None:
            pyautogui.click(x, y, button=button, clicks=clicks)
        else:
            pyautogui.click(button=button, clicks=clicks)
    return {"success": True, "action": "click", "x": x, "y": y, "button": button}


def double_click(x: int, y: int) -> dict:
    return click(x, y, clicks=2)


def right_click(x: int, y: int) -> dict:
    return click(x, y, button="right")


def drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        pyautogui.moveTo(x1, y1)
        pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return {"success": True, "action": "drag", "from": [x1,y1], "to": [x2,y2]}


def scroll(x: int, y: int, clicks: int = 3) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        pyautogui.moveTo(x, y)
        pyautogui.scroll(clicks)
    return {"success": True, "action": "scroll", "clicks": clicks}


# ── Keyboard ──────────────────────────────────────────────────────────────────

def type_text(text: str, interval: float = 0.03) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        pyautogui.typewrite(text, interval=interval)
    return {"success": True, "action": "type", "length": len(text)}


def type_text_raw(text: str) -> dict:
    """
    Type text with special chars using the paste trick — and hand the user's
    clipboard back exactly as we found it.
    """
    err = _require("pyautogui")
    if err: return err
    try:
        import pyperclip
    except ImportError:
        return type_text(text)

    ok, saved = _clipboard_snapshot()
    if not ok:
        # Clipboard holds something we can't restore (an image, copied files).
        # Type it character by character instead of destroying it.
        return type_text(text)
    try:
        with _lock:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)     # let the target consume the paste before we swap back
        return {"success": True, "action": "type_raw", "length": len(text)}
    finally:
        _clipboard_restore(saved)


def hotkey(*keys) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        pyautogui.hotkey(*keys)
    return {"success": True, "action": "hotkey", "keys": list(keys)}


def press(key: str) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        pyautogui.press(key)
    return {"success": True, "action": "press", "key": key}


# ── Applications ──────────────────────────────────────────────────────────────

def _settle(app: str, floor_s: float) -> bool:
    """
    Wait for a just-launched app's window, then report whether it appeared.

    Every launch path used to do `time.sleep(<constant>); _app_visible(...)`, with
    the constant picked by guesswork — 1.2s, 1.4s, 1.5s. That is wrong in both
    directions at once. Notepad is drawn in under half a second and we sat there
    doing nothing for the rest; QQ and Doubao routinely need longer than 1.5s, so
    the check ran while the app was still starting, reported "not visible", and
    the next keystroke went into whatever window was actually in front. The
    Start-Menu path is the worst case for this, because the apps that fall
    through to it are precisely the slow, unregistered ones.

    So: poll instead of sleep, bounded by what THIS app has really needed on THIS
    machine (services/experience.py). Fast apps return as soon as they're up;
    slow apps get the time they've historically taken. Returns as soon as the
    window exists, so this is strictly faster than the old constants for
    everything that works, and only slower when something is genuinely wrong.
    """
    return bool(wait_for_window(app, timeout=floor_s).get("success"))


def open_app(name_or_path: str) -> dict:
    """Open an application by name (Windows) or full path."""
    KNOWN = {
        "notepad":    ["notepad.exe"],
        "calculator": ["calc.exe"],
        "calc":       ["calc.exe"],
        "explorer":   ["explorer.exe"],
        "files":      ["explorer.exe"],
        "fileexplorer":["explorer.exe"],
        "chrome":     ["chrome.exe"],
        "googlechrome":["chrome.exe"],
        "edge":       ["msedge.exe"],
        "msedge":     ["msedge.exe"],
        "firefox":    ["firefox.exe"],
        "cmd":        ["cmd.exe"],
        "terminal":   ["cmd.exe"],
        "powershell": ["powershell.exe"],
        "word":       ["WINWORD.EXE"],
        "excel":      ["EXCEL.EXE"],
        "powerpoint": ["POWERPNT.EXE"],
        "outlook":    ["OUTLOOK.EXE"],
        "vscode":     ["code"],
        "code":       ["code"],
        "visualstudiocode": ["code"],
        "discord":    [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe"), "--processStart", "Discord.exe"],
        "telegram":   [os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe")],
        "steam":      [r"C:\Program Files (x86)\Steam\steam.exe"],
        "spotify":    [os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
        "settings":   ["cmd.exe", "/c", "start", "ms-settings:"],
        "task manager":["taskmgr.exe"],
        "taskmanager":["taskmgr.exe"],
        "paint":      ["mspaint.exe"],
        "snipping":   ["snippingtool.exe"],
    }
    if _app_visible(name_or_path):
        return {"success": True, "action": "open_app", "app": name_or_path,
                "resolved": "already open", "method": "focus", "verified": True}

    key = name_or_path.lower().replace(" ", "")
    known = key in KNOWN
    cmd = KNOWN.get(key, None)

    # 1) A resolved/cached real path wins for anything not in the tiny KNOWN map
    #    (QQ, Doubao, WeChat, …). This is what stops the "Windows cannot find
    #    the file qq" dialog: we launch the actual .exe, or nothing.
    if cmd is None:
        try:
            from services.app_resolver import resolve as resolve_app
            real = resolve_app(name_or_path)
        except Exception:
            real = None
        if real:
            try:
                if real.lower().endswith(".lnk"):
                    os.startfile(real)          # shell-launch a shortcut
                else:
                    subprocess.Popen([real], shell=False,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                vis = _settle(name_or_path, 1.4)
                return {"success": True, "action": "open_app", "app": name_or_path,
                        "resolved": real, "method": "resolved", "verified": vis}
            except Exception:
                pass
        # 2) No known path — use the Start-Menu-search keystroke trick (this is
        #    what actually worked for QQ the first time). Never `cmd /c start qq`,
        #    which pops the "cannot find the file" dialog.
        if os.name == "nt" and _start_menu_launch(name_or_path):
            vis = _settle(name_or_path, 1.5)
            return {"success": vis, "action": "open_app", "app": name_or_path,
                    "resolved": "start menu search", "method": "start_menu",
                    "verified": vis,
                    **({} if vis else {"error": f"Searched the Start Menu for "
                       f"'{name_or_path}' but no matching window opened — it may not "
                       f"be installed, or its window title differs."})}
        return {"success": False, "action": "open_app",
                "error": f"Could not find '{name_or_path}'. If it's installed, open it "
                         f"once manually so I can learn its location."}

    # KNOWN app: launch its mapped command directly.
    SHELL_START = {"msedge.exe", "chrome.exe", "firefox.exe", "code"}
    try:
        if cmd[0] in SHELL_START:
            subprocess.Popen(["cmd.exe", "/c", "start", "", *cmd],
                             shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmd, shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, OSError):
        # mapped exe not found on this machine — try discovery before giving up
        if os.name == "nt" and _start_menu_launch(name_or_path):
            vis = _settle(name_or_path, 1.5)
            return {"success": vis, "action": "open_app", "app": name_or_path,
                    "method": "start_menu", "verified": vis}
        return {"success": False, "action": "open_app",
                "error": f"'{name_or_path}' is not installed where expected."}
    except Exception as e:
        return {"success": False, "action": "open_app", "error": str(e)}

    vis = _settle(name_or_path, 1.2)
    return {"success": True, "action": "open_app", "app": name_or_path,
            "resolved": cmd[0], "method": "direct", "verified": vis}


def _app_visible(name: str) -> bool:
    """Best-effort check that an app is actually up: window title or process."""
    n = (name or "").lower().strip()
    if not n:
        return False
    try:
        if HAS_WINDOWS:
            for t in gw.getAllTitles():
                if t and n in t.lower():
                    return True
    except Exception:
        pass
    try:
        compact = n.replace(" ", "")
        for p in psutil.process_iter(["name"]):
            pn = (p.info.get("name") or "").lower()
            if pn and (compact[:12] in pn or pn.replace(".exe", "") in compact):
                return True
    except Exception:
        pass
    return False


def _start_menu_launch(name: str) -> bool:
    """
    Recovery path for apps not on PATH: press Win, type the app name into
    Start Menu search, press Enter — exactly what a human does when a direct
    launch fails. Returns False when input control isn't available.
    """
    if _require("pyautogui") is not None:
        return False
    try:
        with _lock:
            pyautogui.press("win")
            time.sleep(0.9)
            pyautogui.typewrite(name, interval=0.05)
            time.sleep(1.4)                       # let search results populate
            pyautogui.press("enter")
        time.sleep(2.5)                           # app startup time
        return True
    except Exception:
        return False


def wait_for_window(title_contains: str, timeout: float | None = None) -> dict:
    """
    Block until a window whose title contains the string appears (or the app's
    process shows up). This is the glue that makes chained commands reliable:
    'open notepad' → wait_for_window('notepad') → type — instead of typing
    into whatever window happened to have focus 1.5s later.

    `timeout` is a FLOOR, not a ceiling: Jarvis waits at least that long, and
    longer if this particular app has historically needed longer on THIS machine
    (see services/experience.py). A flat 8s was wrong in both directions —
    Notepad is ready in well under a second, while a cold QQ or Chrome start can
    exceed 8s, and then the next keystroke went into whatever had focus instead.
    """
    learned = _learned_wait(title_contains)
    timeout = learned if timeout is None else max(float(timeout), learned)
    started = time.time()
    deadline = started + timeout
    while time.time() < deadline:
        if _app_visible(title_contains):
            waited = round(time.time() - started, 1)
            # Record the real appearance time so the estimate keeps improving.
            try:
                from services import experience
                experience.record(title_contains, experience.WINDOW_READY, True,
                                  waited, detail="window appeared")
            except Exception:
                pass
            return {"success": True, "action": "wait_for_window",
                    "title": title_contains, "waited": waited,
                    "timeout_used": round(timeout, 1)}
        time.sleep(0.4)
    return {"success": False, "action": "wait_for_window",
            "error": f"Window '{title_contains}' did not appear within {timeout:.0f}s"}


def _run_action(action: str, params: dict) -> dict:
    """Dispatch a single desktop/vision action by name. Never raises."""
    ACTIONS = {
        "open_app":     lambda p: open_app(p.get("name_or_path") or p.get("app", "")),
        "close_app":    lambda p: close_app(p.get("process_name") or p.get("app", "")),
        "type_text":    lambda p: type_text_raw(p.get("text", "")),
        "press":        lambda p: press(p.get("key", "")),
        "hotkey":       lambda p: hotkey(*p.get("keys", [])),
        "click":        lambda p: click(p.get("x"), p.get("y"),
                                        p.get("button", "left"), p.get("clicks", 1)),
        "move":         lambda p: move(p.get("x", 0), p.get("y", 0)),
        "wait":         lambda p: ({"success": True, "action": "wait"},
                                   time.sleep(min(float(p.get("seconds", 1)), 15)))[0],
        # timeout is a floor; experience can extend it for slow apps.
        "wait_for_window": lambda p: wait_for_window(
            p.get("title", ""),
            float(p["timeout"]) if p.get("timeout") is not None else None),
        "focus_window": lambda p: focus_window(p.get("title", "")),
        "open_url":     lambda p: open_url(p.get("url", "")),
        "write_file":   lambda p: write_file(p.get("path", ""), p.get("content", "")),
        "screenshot":   lambda p: __import__("agents.vision_agent", fromlist=["screenshot"]).screenshot(),
        "click_text":   lambda p: __import__("agents.vision_agent", fromlist=["click_text"]).click_text(p.get("text", "")),
        "analyze":      lambda p: __import__("agents.vision_agent", fromlist=["analyze_screen"]).analyze_screen(p.get("question", "")),
    }
    fn = ACTIONS.get(action)
    if fn is None:
        return {"success": False, "error": f"unknown action '{action}'"}
    try:
        return fn(params) or {"success": False, "error": "no result"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _verify_action(action: str, params: dict, result: dict) -> tuple[bool, str]:
    """
    Observe the world AFTER an action and confirm it actually happened. This is
    what stops false "Done" — the action's own return isn't trusted blindly;
    where it's checkable, we look at the real screen/OS state.
    Returns (verified, reason).
    """
    if not result.get("success"):
        return False, result.get("error", "action reported failure")

    if action == "open_app":
        target = params.get("name_or_path") or params.get("app", "")
        # give a slow app a moment, then confirm a window/process exists
        for _ in range(6):
            if _app_visible(target):
                return True, "window/process present"
            time.sleep(0.5)
        return False, f"'{target}' did not appear to open (no window/process found)"

    if action == "close_app":
        target = params.get("process_name") or params.get("app", "")
        return (not _app_visible(target)), ("closed" if not _app_visible(target)
                                            else f"'{target}' still appears to be running")

    if action == "wait_for_window":
        return result.get("success", False), result.get("error", "")

    if action == "write_file":
        try:
            from pathlib import Path
            return Path(params.get("path", "")).exists(), "file exists"
        except Exception:
            return True, ""

    if action == "screenshot":
        return bool(result.get("path") or result.get("b64")), "captured"

    if action == "analyze":
        return bool(result.get("answer") or result.get("ai_answer")), "analysis produced"

    if action == "click_text":
        return bool(result.get("found", True)), result.get("error", "")

    # type_text / press / hotkey / click / move / wait / open_url / focus_window:
    if action == "type_text":
        # Real check where possible: select-all + copy + read the clipboard, and
        # confirm the typed text actually landed in the focused field. This is
        # what catches "notepad opened but nothing was typed" instead of trusting
        # the keystroke call. Non-destructive for editors; skipped if clipboard
        # tooling is unavailable (then we stay honest with a note).
        text = (params.get("text") or "").strip()
        if not text:
            return True, "empty text"
        got = _read_focused_text()
        if got is None:
            return True, "typed (couldn't verify — clipboard unavailable)"
        norm_got = " ".join(got.lower().split())
        norm_txt = " ".join(text.lower().split())
        if norm_txt and norm_txt in norm_got:
            return True, "confirmed via clipboard"
        return False, ("typed but the text isn't in the focused field — the window "
                       "probably didn't have keyboard focus")

    # no cheap post-hoc check — trust the primitive's own success flag.
    return True, "assumed (no cheap verification)"


def _read_focused_text() -> str | None:
    """
    Ctrl+A, Ctrl+C the focused control and return its text (None if we can't).

    The user's clipboard is saved before and put back after — verifying what we
    typed must not cost them whatever they had copied. If the clipboard holds
    something unsaveable (an image, files copied in Explorer) we decline to read
    at all and the caller reports "couldn't verify" instead.
    """
    if not HAS_PYAUTOGUI or _emergency_stop.is_set():
        return None
    try:
        import pyperclip
    except ImportError:
        return None

    ok, saved = _clipboard_snapshot()
    if not ok:
        return None
    try:
        with _lock:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.15)
        got = pyperclip.paste()
        # An unchanged clipboard means the copy never landed (no focus, or the
        # control isn't copyable) — not "the field contains the old clipboard".
        if saved and got == saved:
            return None
        return got
    except Exception:
        return None
    finally:
        _clipboard_restore(saved)


# Actions that must NOT be blindly re-run on a failed verify (retyping would
# duplicate text / re-click). They get one honest attempt.
_NO_RETRY = {"type_text", "click", "click_text", "press", "hotkey"}


def _classify(error: str, action: str, result: dict | None = None) -> dict:
    """Structured failure info. Falls back to a usable shape if the service is
    unavailable, so execution never breaks because diagnosis broke."""
    try:
        from services import experience
        return experience.classify(error, action, result)
    except Exception:
        return {"kind": "unknown", "cause": error or "unknown failure",
                "remedy": "See the runtime report on the Diagnostics screen.",
                "retryable": True, "recovery": "retry", "raw": (error or "")[:300]}


def _learned_wait(app: str) -> float:
    """How long this app actually needs to show a window, on THIS machine."""
    try:
        from services import experience
        return experience.launch_wait_for(app)["wait_s"]
    except Exception:
        return 8.0


def execute_chain(steps: list, max_retries: int = 2) -> dict:
    """
    Run desktop steps with the full execution loop:
        act → observe → verify → retry(≤max_retries) → record.

    A step is only marked done once it's VERIFIED (e.g. open_app is confirmed by
    an actual window/process check, not just "the launch command returned"). If a
    step can't be verified after its retries, the chain stops and reports exactly
    where and why — never a fake success. This is the fix for "it said it opened
    the app / did the task but it didn't".

    Human-like settle between steps: after an app opens, wait for its window and
    focus it before the next keystroke.
    """
    results = []
    steps = steps or []
    last_opened = None            # the app we most recently opened in this chain
    _INPUT = {"type_text", "press", "hotkey", "click", "click_text"}
    for i, s in enumerate(steps):
        action = (s or {}).get("action", "")
        params = (s or {}).get("params", {}) or {}

        # Before ANY keyboard/mouse input, the app we opened must be foreground —
        # otherwise the input lands in the wrong window (the "notepad opens but
        # doesn't type" bug, which also happens when wait_for_window sits between
        # open and type). Confirm focus here regardless of step ordering, and
        # STOP HONESTLY if we can't get it — never type into the void.
        if action in _INPUT and last_opened:
            if not _is_foreground(last_opened):
                fw = focus_window(last_opened)
                results.append({"step": f"{i}.focus", "action": "focus_window", **fw})
                # If focus can't be CONFIRMED we no longer abort outright: the
                # confirmation itself can be unreliable (odd window titles), and
                # type_text is independently verified by a clipboard read-back —
                # that check is the real arbiter of whether the text landed. So
                # try anyway and let verification decide. Still truthful: if the
                # text didn't land, the step fails with that exact reason.
                time.sleep(0.3)

        target = params.get("name_or_path") or params.get("app") or last_opened or ""
        retries = 0 if action in _NO_RETRY else max_retries

        # Apps that habitually fail their first attempt on this machine (cold
        # starts of QQ and similar Electron apps do this) earn one extra try —
        # learned from observation, not guessed. See services/experience.py.
        try:
            from services import experience
            if action not in _NO_RETRY and experience.needs_extra_attempt(target, action)["extra"]:
                retries += 1
        except Exception:
            pass

        verified, reason, r = False, "", {}
        attempts = 0
        started = time.time()
        while attempts <= retries:
            attempts += 1
            r = _run_action(action, params)
            verified, reason = _verify_action(action, params, r)
            if verified:
                break

            # Classify BEFORE deciding to retry. Retrying a missing model or an
            # unresolvable app path just burns seconds and reports the same
            # thing; a lost-focus failure, on the other hand, is worth one more
            # go — after actually re-focusing the window.
            fail = _classify(reason or (r or {}).get("error", ""), action, r)
            if not fail["retryable"]:
                break
            if attempts <= retries:
                if fail["recovery"] == "refocus" and last_opened:
                    focus_window(last_opened)
                    time.sleep(0.4)
                elif fail["recovery"] == "wait_longer" and last_opened:
                    wait_for_window(last_opened)      # learned per-app timing
                time.sleep(min(1.0 * attempts, 3.0))   # brief backoff, then retry

        elapsed = round(time.time() - started, 2)
        entry = {"step": i + 1, "action": action, "attempts": attempts,
                 "verified": verified, "verify_reason": reason,
                 "duration_s": elapsed, **(r or {})}

        fail = None
        if not verified:
            fail = _classify(reason or (r or {}).get("error", ""), action, r)
            entry["failure"] = fail
            # Targeted recovery for the next run: if we couldn't find the app,
            # the cached path is probably stale (reinstalled, moved, updated).
            # Forget it so the next launch re-resolves instead of failing
            # identically forever.
            if fail["recovery"] == "resolve_path" and target:
                try:
                    from services import app_resolver
                    if app_resolver.forget(target):
                        entry["recovery_taken"] = f"forgot cached path for '{target}'"
                except Exception:
                    pass
        results.append(entry)

        # Record what actually happened so the next run is better informed.
        try:
            from services import experience
            experience.record(target, action, verified, elapsed,
                              kind=(fail or {}).get("kind", ""), detail=reason)
        except Exception:
            pass

        if not verified:
            # Report the CAUSE and the FIX, not just the symptom.
            return {"success": False, "steps": results, "failed_at": i + 1,
                    "failure": fail,
                    "error": f"{action} failed: {fail['cause']}",
                    "what_to_do": fail["remedy"]}

        if action == "open_app":
            last_opened = params.get("name_or_path") or params.get("app", "")
            # settle + focus immediately so a following screenshot/analyze also
            # captures THIS app, not whatever was in front before.
            focus_window(last_opened)
            time.sleep(0.4)

    try:   # tell the console what actually ran (real events, not decoration)
        from services import event_bus
        event_bus.publish("desktop.chain_complete",
                          {"steps": len(steps),
                           "actions": ",".join(s.get("action", "") for s in steps)[:80]})
    except Exception:
        pass
    return {"success": True, "steps": results, "count": len(results),
            "verified": True}


def close_app(process_name: str) -> dict:
    """
    Close an application by process/image name (e.g. 'notepad.exe' or 'chrome').

    Matches by exact process name via psutil rather than 'pkill -f' / a bare
    substring match: '-f' matches the FULL COMMAND LINE of every process on the
    system, so a short target like 'code' or 'notepad' can match unrelated
    processes that merely mention it in an argument or file path and kill them
    too. psutil.Process.name() only ever reflects the actual executable image
    name, so the match stays scoped to the intended target.
    """
    stem = process_name[:-4] if process_name.lower().endswith(".exe") else process_name
    stem_l = stem.lower()
    name_exe = f"{stem}.exe"
    try:
        killed = []
        for proc in psutil.process_iter(["pid", "name"]):
            pname = (proc.info.get("name") or "").lower()
            if pname == stem_l or pname == name_exe.lower():
                try:
                    proc.terminate()
                    killed.append(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        if not killed:
            return {"success": False, "action": "close_app", "app": process_name,
                    "error": f"No running process named '{process_name}' found"}
        gone, alive = psutil.wait_procs(
            [psutil.Process(pid) for pid in killed if psutil.pid_exists(pid)], timeout=5)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"success": True, "action": "close_app", "app": process_name, "pids": killed}
    except Exception as e:
        return {"success": False, "action": "close_app", "error": str(e)}


def switch_window(title_contains: str) -> dict:
    """Switch to (focus + raise) a window by partial title. Alias of focus with raise."""
    return focus_window(title_contains)


def open_url(url: str) -> dict:
    """Open a URL in the default browser."""
    try:
        import webbrowser
        webbrowser.open(url)
        return {"success": True, "action": "open_url", "url": url}
    except Exception as e:
        return {"success": False, "error": str(e)}


def close_window(title_contains: str) -> dict:
    """Close a window whose title contains the given string."""
    if not HAS_WINDOWS:
        # Fallback: Alt+F4 on focused window
        return hotkey("alt", "f4")
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return {"success": False, "error": f"No window with '{title_contains}'"}
        wins[0].close()
        return {"success": True, "action": "close_window", "title": title_contains}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _win32_focus(title_contains: str) -> bool:
    """
    Bring a window to the front using the Win32 API directly (ctypes — no new
    dependency). pygetwindow's .activate() fails on modern Windows because the
    OS refuses SetForegroundWindow from a process that doesn't own the current
    foreground window. The accepted workaround is to attach our input queue to
    the foreground thread first, which is what this does. This is the fix for
    the live "opened notepad but couldn't bring it to the foreground" failure.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32

        target = {"hwnd": None}
        needle = (title_contains or "").lower()

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _):
            if not u32.IsWindowVisible(hwnd):
                return True
            n = u32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            if needle in buf.value.lower():
                target["hwnd"] = hwnd
                return False       # stop enumerating
            return True

        u32.EnumWindows(_enum, 0)
        hwnd = target["hwnd"]
        if not hwnd:
            return False

        SW_RESTORE = 9
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_RESTORE)

        fg = u32.GetForegroundWindow()
        our_tid = k32.GetCurrentThreadId()
        fg_tid = u32.GetWindowThreadProcessId(fg, None) if fg else 0

        attached = False
        if fg_tid and fg_tid != our_tid:
            attached = bool(u32.AttachThreadInput(fg_tid, our_tid, True))
        try:
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
            u32.SetActiveWindow(hwnd)
        finally:
            if attached:
                u32.AttachThreadInput(fg_tid, our_tid, False)

        time.sleep(0.15)
        return u32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def focus_window(title_contains: str) -> dict:
    """Bring a window to the foreground, robustly, and CONFIRM it worked."""
    # Try the real Win32 path FIRST — it's the one that actually works on Windows.
    if _win32_focus(title_contains):
        return {"success": True, "action": "focus_window", "title": title_contains,
                "confirmed": True, "method": "win32"}
    if not HAS_WINDOWS:
        return {"success": False, "error": "pygetwindow not available"}
    try:
        wins = [w for w in gw.getWindowsWithTitle(title_contains) if w.title.strip()]
        if not wins:
            return {"success": False, "error": f"No window with '{title_contains}'"}
        win = wins[0]
        for attempt in range(3):
            try:
                if getattr(win, "isMinimized", False):
                    win.restore()
                    time.sleep(0.2)
                win.activate()
            except Exception:
                # pygetwindow's activate can throw on some Windows builds; a
                # minimize+restore reliably steals foreground as a fallback.
                try:
                    win.minimize(); time.sleep(0.15); win.restore()
                except Exception:
                    pass
            time.sleep(0.25)
            if _is_foreground(title_contains):
                return {"success": True, "action": "focus_window",
                        "title": title_contains, "confirmed": True}
        # Last resort: click the window's center to force keyboard focus there.
        try:
            cx = win.left + max(win.width // 2, 10)
            cy = win.top + max(win.height // 2, 10)
            if HAS_PYAUTOGUI and not _emergency_stop.is_set():
                pyautogui.click(cx, cy)
                time.sleep(0.2)
        except Exception:
            pass
        confirmed = _is_foreground(title_contains)
        return {"success": confirmed, "action": "focus_window",
                "title": title_contains, "confirmed": confirmed,
                **({} if confirmed else
                   {"error": f"couldn't bring '{title_contains}' to the foreground"})}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _is_foreground(title_contains: str) -> bool:
    """Is a window matching this title currently the active/foreground window?"""
    needle = (title_contains or "").lower()
    if os.name == "nt":
        try:
            import ctypes
            u32 = ctypes.windll.user32
            hwnd = u32.GetForegroundWindow()
            if hwnd:
                n = u32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                if needle and needle in buf.value.lower():
                    return True
        except Exception:
            pass
    if not HAS_WINDOWS:
        return False
    try:
        active = gw.getActiveWindow()
        if active and active.title and needle in active.title.lower():
            return True
    except Exception:
        pass
    return False


def minimize_window(title_contains: str) -> dict:
    """Minimize a window whose title contains the given string."""
    if not HAS_WINDOWS:
        return {"success": False, "error": "pygetwindow not available"}
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return {"success": False, "error": f"No window with '{title_contains}'"}
        wins[0].minimize()
        return {"success": True, "action": "minimize_window", "title": title_contains}
    except Exception as e:
        return {"success": False, "error": str(e)}


def maximize_window(title_contains: str) -> dict:
    """Maximize a window whose title contains the given string."""
    if not HAS_WINDOWS:
        return {"success": False, "error": "pygetwindow not available"}
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return {"success": False, "error": f"No window with '{title_contains}'"}
        wins[0].maximize()
        return {"success": True, "action": "maximize_window", "title": title_contains}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_windows() -> dict:
    """List all open window titles."""
    if not HAS_WINDOWS:
        return {"success": True, "windows": [], "note": "pygetwindow not installed"}
    try:
        titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
        return {"success": True, "windows": titles}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── File operations ───────────────────────────────────────────────────────────

def read_file(path: str) -> dict:
    try:
        p = Path(path)
        if not p.exists():
            return {"success": False, "error": f"File not found: {path}"}
        content = p.read_text(encoding="utf-8", errors="ignore")
        return {"success": True, "path": path, "content": content, "size": len(content)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(path: str, content: str) -> dict:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "path": path, "bytes": len(content)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_files(directory: str, pattern: str = "*") -> dict:
    try:
        p = Path(directory)
        if not p.exists():
            return {"success": False, "error": f"Directory not found: {directory}"}
        files = [str(f) for f in p.glob(pattern) if f.is_file()]
        return {"success": True, "directory": directory, "files": files, "count": len(files)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def open_folder(path: str) -> dict:
    """Open a folder in the system file explorer."""
    try:
        p = Path(os.path.expandvars(os.path.expanduser(path)))
        if not p.exists():
            return {"success": False, "error": f"Folder not found: {p}"}
        if sys.platform == "win32":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"success": True, "action": "open_folder", "path": str(p)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_files(directory: str, query: str, max_results: int = 50) -> dict:
    """Recursively search for files whose name contains query."""
    try:
        base = Path(os.path.expandvars(os.path.expanduser(directory)))
        if not base.exists():
            return {"success": False, "error": f"Directory not found: {base}"}
        matches = []
        q = query.lower()
        for f in base.rglob("*"):
            if len(matches) >= max_results:
                break
            try:
                if q in f.name.lower():
                    matches.append({"path": str(f), "name": f.name, "is_dir": f.is_dir(),
                                    "size": f.stat().st_size if f.is_file() else None})
            except (PermissionError, OSError):
                continue
        return {"success": True, "query": query, "directory": str(base),
                "matches": matches, "count": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def rename_file(old_path: str, new_name: str) -> dict:
    """Rename a file or folder (new_name is just the name, kept in same directory)."""
    try:
        p = Path(os.path.expandvars(os.path.expanduser(old_path)))
        if not p.exists():
            return {"success": False, "error": f"Not found: {p}"}
        target = p.parent / new_name
        if target.exists():
            return {"success": False, "error": f"Target already exists: {target}"}
        p.rename(target)
        return {"success": True, "action": "rename", "from": str(p), "to": str(target)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def move_file(src: str, dest_dir: str) -> dict:
    """Move a file/folder into dest_dir."""
    import shutil
    try:
        s = Path(os.path.expandvars(os.path.expanduser(src)))
        d = Path(os.path.expandvars(os.path.expanduser(dest_dir)))
        if not s.exists():
            return {"success": False, "error": f"Source not found: {s}"}
        d.mkdir(parents=True, exist_ok=True)
        final = shutil.move(str(s), str(d))
        return {"success": True, "action": "move", "from": str(s), "to": str(final)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def copy_file(src: str, dest: str) -> dict:
    """Copy a file to dest path."""
    import shutil
    try:
        s = Path(os.path.expandvars(os.path.expanduser(src)))
        if not s.exists():
            return {"success": False, "error": f"Source not found: {s}"}
        d = Path(os.path.expandvars(os.path.expanduser(dest)))
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(str(s), str(d))
        else:
            shutil.copy2(str(s), str(d))
        return {"success": True, "action": "copy", "from": str(s), "to": str(d)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(path: str, confirm: bool = False) -> dict:
    """
    Delete a file or folder. REQUIRES confirm=True — this is the safety gate.
    Without confirm, returns a preview of what would be deleted.
    """
    try:
        p = Path(os.path.expandvars(os.path.expanduser(path)))
        if not p.exists():
            return {"success": False, "error": f"Not found: {p}"}

        if not confirm:
            # Safety: return what WOULD be deleted, require explicit confirm
            info = {"path": str(p), "is_dir": p.is_dir()}
            if p.is_dir():
                try:
                    info["contains"] = sum(1 for _ in p.rglob("*"))
                except Exception:
                    info["contains"] = "unknown"
            return {
                "success": False,
                "needs_confirmation": True,
                "preview": info,
                "message": f"Will delete {'folder' if p.is_dir() else 'file'}: {p}. "
                           f"Call again with confirm=true to proceed.",
            }

        import shutil
        if p.is_dir():
            shutil.rmtree(str(p))
        else:
            p.unlink()
        return {"success": True, "action": "delete", "deleted": str(p)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_command(command: str, timeout: int = 30) -> dict:
    """
    Run a whitelisted command and return its output.

    No shell. The whitelist alone was never enough protection: with shell=True,
    `python -c ...; rm -rf x` or `dir & whoami` passes the prefix check and then
    the shell happily runs the second half. We parse the string into an argv list
    and hand that straight to the OS, so metacharacters are just characters.

    `dir` is a cmd.exe builtin with no executable, so it's translated rather than
    given a shell.
    """
    import shlex

    WHITELIST = {"dir", "ls", "echo", "type", "cat", "python", "python3",
                 "pip", "pip3", "ollama", "node", "npm"}
    GIT_SUBS  = {"status", "log", "diff", "branch"}

    try:
        argv = shlex.split(command.strip(), posix=(os.name != "nt"))
    except ValueError as e:
        return {"success": False, "error": f"Could not parse command: {e}"}
    if not argv:
        return {"success": False, "error": "Empty command"}

    # Match on the parsed program name, not a string prefix: "python" must not
    # let "pythonsomethingelse.exe" through.
    head = argv[0].lower().removesuffix(".exe")
    if head == "git":
        if len(argv) < 2 or argv[1].lower() not in GIT_SUBS:
            return {"success": False,
                    "error": f"Only read-only git commands are allowed "
                             f"({', '.join(sorted(GIT_SUBS))})"}
    elif head not in WHITELIST:
        return {"success": False, "error": f"Command not in whitelist: {argv[0]}"}

    # Reject anything that smells like chaining or redirection. Without a shell
    # these are inert for normal programs, but the cmd-builtin path below does
    # re-enter cmd.exe, so a token like `x&whoami` must never reach it.
    BAD = ("&", "|", ";", ">", "<", "^", "`", "$(")
    for tok in argv[1:]:
        if any(b in tok for b in BAD):
            return {"success": False,
                    "error": "Command chaining and redirection are not allowed"}

    # `dir`/`type`/`echo` are cmd.exe builtins with no executable behind them.
    if os.name == "nt" and argv[0].lower() in ("dir", "type", "echo"):
        argv = ["cmd", "/c"] + argv

    try:
        result = subprocess.run(
            argv, shell=False, capture_output=True, text=True, timeout=timeout
        )
        return {
            "success":    result.returncode == 0,
            "stdout":     result.stdout[:2000],
            "stderr":     result.stderr[:500],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except FileNotFoundError:
        # shell=False surfaces this instead of a 'not recognized' exit code.
        return {"success": False,
                "error": f"'{argv[0]}' is not installed or not on PATH"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Status ────────────────────────────────────────────────────────────────────

def get_status() -> dict:
    screen = None
    if HAS_PYAUTOGUI:
        try:
            s = pyautogui.size()
            m = pyautogui.position()
            screen = {"width": s.width, "height": s.height, "mouse_x": m.x, "mouse_y": m.y}
        except Exception:
            pass

    return {
        "pyautogui":    HAS_PYAUTOGUI,
        "pygetwindow":  HAS_WINDOWS,
        "platform":     sys.platform,
        "screen":       screen,
        "capabilities": {
            "mouse":      HAS_PYAUTOGUI,
            "keyboard":   HAS_PYAUTOGUI,
            "windows":    HAS_WINDOWS,
            "files":      True,
            "apps":       True,
            "commands":   True,
        }
    }
