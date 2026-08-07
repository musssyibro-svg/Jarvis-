"""
backend/agents/desktop_agent.py
Full desktop control: mouse, keyboard, window management, file ops.
Uses PyAutoGUI + PyWinAuto (Windows) with graceful fallback.
"""
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from services import trace

# ── Safe imports ──────────────────────────────────────────────────────────────
#
# `except Exception`, not `except ImportError`, and that distinction is the
# whole point.
#
# pyautogui is INSTALLED and still fails to import when there is no display:
# it pulls in mouseinfo, which does `Display(os.environ['DISPLAY'])` at module
# scope and raises KeyError('DISPLAY'). That is not an ImportError, so the old
# guard didn't catch it — and importing desktop_agent crashed outright instead
# of degrading to HAS_PYAUTOGUI = False.
#
# CLAUDE.md: a missing optional dependency is a SKIP with an install hint, not
# a failure. "Installed but unusable here" is the same situation and deserves
# the same treatment. Found by CI on a headless runner; it never reproduced
# locally, because locally pyautogui simply wasn't installed and the
# ImportError path worked fine.
try:
    import pyautogui
    pyautogui.FAILSAFE = True   # Move mouse to top-left to abort
    pyautogui.PAUSE    = 0.05
    HAS_PYAUTOGUI = True
    _NO_INPUT_REASON = ""
except Exception as _e:
    HAS_PYAUTOGUI = False
    # Keep WHY, so the error names the real cause. "Run: pip install pyautogui"
    # is actively misleading when the package is installed and the display is
    # missing — it sends the user off to install something they already have.
    _NO_INPUT_REASON = (
        "pyautogui is not installed. Run: pip install pyautogui"
        if isinstance(_e, ImportError) else
        f"pyautogui is installed but can't start here ({type(_e).__name__}: "
        f"{_e}). On Windows that usually means no interactive desktop session — "
        f"Jarvis must run as you, not as a service."
    )

try:
    import pygetwindow as gw
    HAS_WINDOWS = True
except Exception:      # same reason: pygetwindow needs a window system
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
        return {"success": False, "error": _NO_INPUT_REASON}
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


# ── Did anything actually happen? ────────────────────────────────────────────
#
# A click "succeeds" the moment pyautogui returns, which tells you the mouse
# moved — not that anything responded. Clicking a disabled button, a stale
# coordinate, or a window that closed half a second ago all return success.
# Everything downstream then proceeds as if the UI had changed.
#
# So: look at a small patch of screen around the click, before and after. If
# NOTHING changed, the click landed on nothing. Cheap on purpose — a 240px box
# downscaled to a thumbnail, not a full screengrab: this runs after every click
# on a 16 GB machine, and a full-screen capture per click is how vision once
# cost 288 seconds.

_OBSERVE_BOX = 240          # pixels around the point we watch
_OBSERVE_THUMB = 24         # downscale to this before comparing
_OBSERVE_CHANGED = 6        # mean per-pixel delta that counts as "something moved"


def _peek(x: int | None, y: int | None):
    """A tiny fingerprint of the screen near (x, y). None if we can't look."""
    from agents.vision_agent import HAS_MSS, HAS_PIL
    if not (HAS_MSS and HAS_PIL):
        return None
    try:
        import mss
        from PIL import Image
        with mss.mss() as sct:
            mon = sct.monitors[0]
            if x is None or y is None:
                box = mon
            else:
                half = _OBSERVE_BOX // 2
                box = {"left": max(mon["left"], int(x) - half),
                       "top": max(mon["top"], int(y) - half),
                       "width": _OBSERVE_BOX, "height": _OBSERVE_BOX}
            raw = sct.grab(box)
        img = Image.frombytes("RGB", raw.size, raw.rgb).convert("L")
        return img.resize((_OBSERVE_THUMB, _OBSERVE_THUMB)).tobytes()
    except Exception:
        return None


def _changed(before, after) -> bool | None:
    """True/False if we could compare, None if we couldn't see."""
    if before is None or after is None or len(before) != len(after):
        return None
    delta = sum(abs(a - b) for a, b in zip(before, after, strict=True)) / len(before)
    return delta >= _OBSERVE_CHANGED


# ── Mouse ─────────────────────────────────────────────────────────────────────

def move(x: int, y: int, duration: float = 0.3) -> dict:
    err = _require("pyautogui")
    if err: return err
    with _lock:
        pyautogui.moveTo(x, y, duration=duration)
    return {"success": True, "action": "move", "x": x, "y": y}


def click(x: int = None, y: int = None, button: str = "left", clicks: int = 1,
          verify: bool = True) -> dict:
    """
    Click, then check whether the screen responded.

    `success` means the click was issued. `verified` means something on screen
    actually changed underneath it. They are different facts and are reported
    separately — a click that hit a dead pixel is still `success: True`, and
    saying so is the honest answer.
    """
    err = _require("pyautogui")
    if err: return err

    before = _peek(x, y) if verify else None
    fg_before = _foreground_id()
    with _lock:
        if x is not None and y is not None:
            pyautogui.click(x, y, button=button, clicks=clicks)
        else:
            pyautogui.click(button=button, clicks=clicks)

    out = {"success": True, "action": "click", "x": x, "y": y, "button": button}
    if not verify:
        return out

    time.sleep(0.25)        # let the UI redraw before judging it
    moved = _changed(before, _peek(x, y))
    fg_after = _foreground_id()

    if moved is None and fg_before == fg_after:
        # No eyes. Don't claim, and don't pretend the claim is a small thing.
        out.update(verified=False, verify_reason=(
            "Clicked, but Jarvis can't see the screen here (no mss/Pillow), so "
            "it cannot tell whether anything responded."))
    elif moved or fg_before != fg_after:
        out.update(verified=True, verify_reason=(
            "the window changed" if fg_before != fg_after
            else "the screen under the cursor changed"))
    else:
        out.update(verified=False, verify_reason=(
            f"Nothing on screen changed after clicking ({x}, {y}). The click "
            f"probably landed on nothing — the element may have moved, or the "
            f"window may not have been in front."))
    return out


def _foreground_id() -> str:
    """A cheap identifier for 'which window is in front', or '' if unknown."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return ""
        n = u32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        return f"{hwnd}:{buf.value}"
    except Exception:
        return ""


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


def _observe_keys(fn, out: dict) -> dict:
    """
    Run a keystroke and note whether the screen reacted.

    Same reasoning as click(): pyautogui returning means the key was sent to
    the OS, not that anything received it. Ctrl+S into a window that lost focus
    "succeeds" and saves nothing.

    The whole screen is watched here rather than a box, because a keystroke's
    effect can appear anywhere — a save dialog, a menu, a sent message.
    """
    before = _peek(None, None)
    fg_before = _foreground_id()
    with _lock:                 # `with`, not manual acquire/release — an
        fn()                    # exception inside fn() must not strand the lock
    time.sleep(0.25)
    moved = _changed(before, _peek(None, None))
    fg_after = _foreground_id()

    if moved is None and fg_before == fg_after:
        out.update(verified=False, verify_reason=(
            "Key sent, but Jarvis can't see the screen here (no mss/Pillow), "
            "so it cannot tell whether anything received it."))
    elif moved or fg_before != fg_after:
        out.update(verified=True, verify_reason=(
            "the window changed" if fg_before != fg_after else "the screen changed"))
    else:
        out.update(verified=False, verify_reason=(
            "Nothing on screen changed. The keystroke probably went to a "
            "window that wasn't listening."))
    return out


def hotkey(*keys) -> dict:
    err = _require("pyautogui")
    if err: return err
    return _observe_keys(lambda: pyautogui.hotkey(*keys),
                         {"success": True, "action": "hotkey", "keys": list(keys)})


def press(key: str) -> dict:
    err = _require("pyautogui")
    if err: return err
    return _observe_keys(lambda: pyautogui.press(key),
                         {"success": True, "action": "press", "key": key})


# ── Applications ──────────────────────────────────────────────────────────────

def compose_text(prompt: str, max_words: int = 180) -> dict:
    """
    Generate the text and hand it back WITHOUT typing it.

    Split out of compose_and_type when messaging arrived. Sending a composed
    message is not "generate, then type wherever the caret is" — the text has to
    exist before the chat is chosen, so it can be shown to the user in the
    approval step and compared against the input box afterwards. Two callers,
    one model call, one preamble stripper; the alternative was a second copy of
    this prompt that would drift.

    Returns {"success", "text"|"error"}. On failure `text` is absent and NOTHING
    is typed — falling back to typing the prompt would put the words "about
    yourself" into the user's document, which is the bug this was built to fix.
    """
    topic = (prompt or "").strip()
    if not topic:
        return {"success": False, "error": "nothing to write about"}

    try:
        from services.deepseek_service import call_model
        instruction = (
            f"Write the following, in plain prose, under {max_words} words.\n"
            f"Topic: {topic}\n\n"
            f"Output ONLY the finished text. No preamble, no 'Sure, here is', "
            f"no markdown, no quotes around it, no commentary afterwards."
        )
        text = (call_model(instruction, fast=True, task="chat") or "").strip()
    except Exception as e:
        return {"success": False,
                "error": f"couldn't reach the model: {str(e)[:120]}"}

    # call_model returns its errors as a string rather than raising.
    if not text or text.startswith("[Ollama") or text.startswith("[Anthropic"):
        return {"success": False, "error": text or "the model returned nothing"}

    text = _strip_model_preamble(text)
    if not text:
        return {"success": False,
                "error": "the model replied but produced no usable text"}
    return {"success": True, "text": text, "topic": topic}


def compose_and_type(prompt: str, max_words: int = 180) -> dict:
    """
    Generate text with the LLM, then type it. This is what "open notepad and
    write about yourself" should always have done.

    Kept separate from type_text on purpose. Typing is deterministic and instant;
    composing calls a model, can take seconds, and can fail. Merging them would
    make every literal `type` pay the cost and the risk of a model call.
    """
    got = compose_text(prompt, max_words)
    if not got.get("success"):
        return {"success": False, "action": "compose", "error": got["error"]}
    text = got["text"]
    res = type_text_raw(text)
    res.update(action="compose", topic=got.get("topic", ""), composed=text,
               words=len(text.split()))
    return res


def _strip_model_preamble(text: str) -> str:
    """
    Remove the conversational wrapper small models add no matter how firmly
    they're told not to ("Sure! Here's a short bio:", ```fences```, surrounding
    quotes). Without this the document starts with the model talking to you.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        parts = t.split("```")
        t = (parts[1] if len(parts) > 1 else t).strip()
        if "\n" in t and " " not in t.split("\n", 1)[0]:
            t = t.split("\n", 1)[1].strip()        # drop a language tag line
    lead = re.match(r"^(sure|certainly|of course|okay|ok|here(?:'s| is)|below is)\b[^\n]{0,80}?[:\n]",
                    t, re.IGNORECASE)
    if lead:
        t = t[lead.end():].strip()
    if len(t) > 1 and t[0] in "\"'“" and t[-1] in "\"'”":
        t = t[1:-1].strip()
    return t


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
    # Already running? Then RAISE IT, and report what actually happened.
    #
    # This branch used to return {"method": "focus", "verified": True} without
    # focusing anything and without verifying anything. Both were false. It is
    # the second half of the QQ bug: QQ was already running, this returned
    # "verified", nothing came to the front, and the screenshot that followed
    # captured a different window entirely.
    running = _running_process_for(name_or_path)
    if running:
        raised = focus_window(name_or_path).get("success", False)
        return {"success": True, "action": "open_app", "app": name_or_path,
                "resolved": f"already running as {running}",
                "method": "focus", "verified": bool(raised),
                "foreground": bool(raised),
                **({} if raised else {
                    "warning": f"{name_or_path} is already running as {running}, "
                               f"but it could not be brought to the front. Anything "
                               f"that follows may act on the wrong window."})}

    key = name_or_path.lower().replace(" ", "")
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


def _running_process_for(name: str) -> str | None:
    """
    The EXACT process this app is running as, or None.

    This replaces a substring match that was wrong in both directions and is
    the root of "it opened QQ the first time but never again":

        _app_visible("notepad")  matched  notepad++.exe
        _app_visible("qq")       matched  qqbrowser.exe
        _app_visible("code")     matched  codemeter.exe
        _app_visible("qq")       matched  an Edge tab titled "QQ音乐下载 - Edge"

    open_app() returns "already open" the moment this says yes — so a browser
    tab that merely MENTIONS the app was enough to make Jarvis skip the launch
    entirely, report success, and then screenshot whatever was in front. The
    user saw "no unread messages" from a window that was never QQ.

    Matching is now exact against _process_names_for(), which is alias-aware
    and knows what app_resolver actually launched. One matcher, not two that
    disagree.
    """
    n = (name or "").strip().lower()
    if not n:
        return None
    wanted = _process_names_for(n)
    if not wanted:
        return None
    try:
        for p in psutil.process_iter(["name"]):
            pn = (p.info.get("name") or "").lower()
            if pn and pn in wanted:
                return pn
    except Exception:
        pass
    return None


def _app_visible(name: str) -> bool:
    """
    Is this app actually running?

    Process-based, because window titles are localised (Notepad is 记事本 here)
    AND because a title is not evidence of the app — anyone can open a web page
    called "Microsoft Word Tutorial".

    Titles are still consulted on non-Windows, where there is no reliable
    process mapping, but only as a last resort.
    """
    if _running_process_for(name):
        return True
    if os.name != "nt" and HAS_WINDOWS:
        n = (name or "").strip().lower()
        try:
            return any(t and n in t.lower() for t in gw.getAllTitles())
        except Exception:
            return False
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


def _use_credential(params: dict) -> dict:
    """
    Fill a login that was deliberately NOT recorded.

    When a demonstration passes through a password field, teach.py stores a
    marker instead of the keystrokes. On replay we look for a matching entry in
    the encrypted vault; if there isn't one, we stop and ask rather than typing
    a guess into a real login form. Failing here is correct behaviour, so it
    reports a clear reason and a fix instead of an error.
    """
    label = (params.get("for") or params.get("platform") or "").strip()
    try:
        from services.vault import get_credential
        cred = get_credential(label) if label else None
    except Exception as e:
        return {"success": False, "error": f"vault unavailable: {e}"}
    if not cred or not cred.get("password"):
        return {"success": False,
                "error": f"no saved login for '{label or 'this window'}'",
                "what_to_do": "Add it under Settings -> Logins (it's encrypted on "
                              "this PC), or sign in once by hand — the browser "
                              "profile keeps the session."}
    if u := cred.get("username"):
        type_text_raw(u)
        press("tab")
    type_text_raw(cred["password"])
    # The password itself never appears in the result, the feed or the report.
    return {"success": True, "action": "credential",
            "detail": f"filled saved login for {label}"}


def read_messages(app: str = "", question: str = "") -> dict:
    """
    "What does this app say?" — read the interface, fall back to looking at it.

    Two ways to answer, and they are not equal. Windows hands us the actual text
    of the actual window in milliseconds; a screenshot plus a vision model takes
    55 seconds on this machine (measured, 2026-08-05) and returns a paraphrase.
    So: accessibility tree first, always.

    The fallback is NOT silent. `method` says which path answered and
    `fell_back_because` says why the fast one didn't, because "QQ hides its
    interface from Windows" and "you have no new messages" look identical in a
    summary and mean completely different things. A user who never learns which
    one they got cannot tell a quiet app from a blind assistant.
    """
    from agents import ui_agent
    got = ui_agent.read_messages(app)
    if got.get("success") and got.get("verified") and got.get("messages"):
        msgs = got["messages"]
        return {"success": True, "verified": True, "action": "read_messages",
                "app": app, "method": "accessibility",
                "messages": msgs,
                "detail": "\n".join(msgs),
                "verify_reason": got.get("verify_reason", ""),
                "explanation": f"Read {len(msgs)} entries straight from {app}'s "
                               f"window — this is what it says, not a summary."}

    why = got.get("error") or got.get("verify_reason") or "the window wasn't readable"

    # Falling back to a screenshot is only honest if we were looking at the
    # right window. When the app could not be brought to the front, a photo of
    # the screen is a photo of something else — and the vision model will answer
    # confidently about it. That is precisely the 2026-08-05 report: focus_window
    # failed twice for 'qq', the chain carried on, and Jarvis described Edge.
    if got.get("stage") == "focus":
        return {"success": False, "verified": False, "action": "read_messages",
                "app": app, "method": "none", "error": why,
                "what_to_do": got.get("what_to_do") or
                              f"Bring {app or 'the app'} up yourself and ask "
                              f"again — Jarvis will not photograph a different "
                              f"window and answer about that."}

    from agents import vision_agent
    shot = vision_agent.screenshot()
    if not shot.get("success"):
        # Both ways of looking failed. Reporting an empty inbox here would be
        # the exact lie this function exists to prevent.
        return {"success": False, "verified": False, "action": "read_messages",
                "app": app, "method": "none",
                "error": f"couldn't read {app or 'that window'} ({why}) and "
                         f"couldn't take a screenshot either "
                         f"({shot.get('error', 'no reason given')})",
                "what_to_do": got.get("what_to_do", "")}
    look = vision_agent.analyze_screen(
        question or (f"What new or unread messages are visible in {app}? List each "
                     f"sender and a one-line summary. If none are visible, say so."))
    return {**look, "action": "read_messages", "app": app, "method": "screenshot",
            "fell_back_because": why,
            "verified": False,
            "verify_reason": f"read by looking at the screen, not from {app}'s own "
                             f"window ({why})"}


def send_message(p: dict) -> dict:
    """
    The `send_message` step: compose if asked, then hand off to ui_agent.

    Approval lives here rather than inside ui_agent because it is a policy, not
    a mechanism. Default is "type it, show it, don't send it" — CLAUDE.md is
    explicit that anything which submits needs approval by default, and a
    message to the wrong person is not recoverable by clicking undo. The setting
    exists because the chain now VERIFIES whose chat is open before typing, so
    turning it off is a considered choice rather than a leap.
    """
    text = p.get("text", "")
    if p.get("compose") and text:
        got = compose_text(text, max_words=60)
        if not got.get("success"):
            return {"success": False, "action": "send_message",
                    "error": f"couldn't write the message: {got['error']}",
                    "what_to_do": "Nothing was typed or sent."}
        text = got["text"]

    send = p.get("send")
    if send is None:
        try:
            from services import config
            send = not config.get_bool("messages_need_approval", True)
        except Exception:
            send = False

    from agents import ui_agent
    out = ui_agent.send_message(p.get("app", ""), p.get("contact", ""), text,
                                send=bool(send))
    out["action"] = "send_message"
    return out


def _run_action(action: str, params: dict) -> dict:
    """Dispatch a single desktop/vision action by name. Never raises."""
    ACTIONS = {
        "open_app":     lambda p: open_app(p.get("name_or_path") or p.get("app", "")),
        "close_app":    lambda p: close_app(p.get("process_name") or p.get("app", "")),
        "type_text":    lambda p: type_text_raw(p.get("text", "")),
        # compose = generate with the LLM first, then type the result
        "compose":      lambda p: compose_and_type(p.get("prompt") or p.get("topic", "")),
        "press":        lambda p: press(p.get("key", "")),
        "hotkey":       lambda p: hotkey(*p.get("keys", [])),
        "click":        lambda p: click(p.get("x"), p.get("y"),
                                        p.get("button", "left"), p.get("clicks", 1)),
        "move":         lambda p: move(p.get("x", 0), p.get("y", 0)),
        # Scroll at the pointer's current position unless told otherwise, which
        # is what "scroll down" means when a page is already in front of you.
        "scroll":       lambda p: scroll(
            p.get("x"), p.get("y"),
            -abs(int(p.get("clicks", 3))) if str(p.get("direction", "down")).lower()
            == "down" else abs(int(p.get("clicks", 3)))),
        # A step recorded where the user typed a password. Never replayed from a
        # recording — see services/teach.py.
        "credential":   lambda p: _use_credential(p),
        "wait":         lambda p: ({"success": True, "action": "wait"},
                                   time.sleep(min(float(p.get("seconds", 1)), 15)))[0],
        # timeout is a floor; experience can extend it for slow apps.
        "wait_for_window": lambda p: wait_for_window(
            p.get("title", ""),
            float(p["timeout"]) if p.get("timeout") is not None else None),
        "focus_window": lambda p: focus_window(p.get("title", "")),
        "open_url":     lambda p: open_url(p.get("url", ""), p.get("browser", ""),
                                           p.get("query", "")),
        "write_file":   lambda p: write_file(p.get("path", ""), p.get("content", "")),
        "screenshot":   lambda p: __import__("agents.vision_agent", fromlist=["screenshot"]).screenshot(),
        "click_text":   lambda p: __import__("agents.vision_agent", fromlist=["click_text"]).click_text(p.get("text", "")),
        "analyze":      lambda p: __import__("agents.vision_agent", fromlist=["analyze_screen"]).analyze_screen(p.get("question", "")),
        # ── Reading the interface instead of a picture of it ──────────────
        # These go through agents/ui_agent.py. They are separate actions rather
        # than a smarter `click_text` because they answer a different question:
        # click_text finds a rectangle that looks like some words, ui_click
        # finds the element that IS those words and can say when two of them
        # match. One guesses and cannot know it guessed wrong.
        "read_messages": lambda p: read_messages(p.get("app", ""),
                                                 p.get("question", "")),
        "ui_read":      lambda p: __import__("agents.ui_agent", fromlist=["read_text"]).read_text(p.get("app", "")),
        "ui_click":     lambda p: __import__("agents.ui_agent", fromlist=["click"]).click(p.get("app", ""), p.get("name", ""), p.get("role", "")),
        "send_message": lambda p: send_message(p),
    }
    fn = ACTIONS.get(action)
    if fn is None:
        # Through the contract as well — an unknown action is still a result,
        # and a caller reading `verified` must not get a KeyError on the one
        # path that skipped normalisation.
        return _contract({"success": False,
                          "error": f"unknown action '{action}'"}, action)
    started = time.time()
    try:
        out = fn(params) or {"success": False, "error": "no result"}
    except Exception as e:
        # This used to be `str(e)` and nothing else. For the headless crash that
        # cost an afternoon, `str(e)` was the string 'DISPLAY' — no traceback,
        # no arguments, no way to tell which of twenty actions raised it.
        #
        # The user still sees a short cause-and-fix message; the traceback goes
        # to the diagnostics buffer, with the parameters redacted, because
        # `type_text` params have contained a password.
        import traceback
        rec = trace.failure(f"desktop.{action}", f"{type(e).__name__}: {e}",
                            detail=traceback.format_exc(), **(params or {}))
        trace.record_cost(f"desktop.{action}", (time.time() - started) * 1000)
        return _contract({"success": False, "error": str(e) or type(e).__name__,
                          "exception": type(e).__name__, "diagnostic": rec["at"]},
                         action, time.time() - started)
    trace.record_cost(f"desktop.{action}", (time.time() - started) * 1000)
    return _contract(out, action, time.time() - started)


# ── One shape for every result ───────────────────────────────────────────────

# What every action reports, whatever it did.
#
# Three independent reviews said the same thing and they were right: some
# primitives returned {success, verified, verify_reason}, others just
# {success}, open_url returned a third shape and run_command a fourth. "success"
# therefore meant different things in different places, which is exactly how a
# false ✓ survives — a caller reading `verified` got None from half the system
# and could not tell "not verified" from "this action doesn't report it".
#
# Applied HERE rather than by rewriting twenty primitives, because this is the
# single function every desktop action already passes through. A primitive that
# knows more (click observes the screen, type_text reads the clipboard back)
# still sets its own richer values; this only fills what is missing, and never
# overwrites a real answer with a guess.
_CONTRACT_KEYS = ("success", "verified", "confidence", "proof",
                  "duration_ms", "explanation")


def _contract(result: dict, action: str = "", elapsed_s: float = 0.0) -> dict:
    out = dict(result or {})
    out.setdefault("action", action)
    out["duration_ms"] = int(elapsed_s * 1000)

    ok = bool(out.get("success"))
    # verified is left as None when the action genuinely cannot tell. None is
    # not False: "I didn't check" and "I checked and it hadn't happened" send
    # the user to completely different places, and collapsing them was half of
    # the original complaint.
    if "verified" not in out:
        out["verified"] = None if ok else False

    if "confidence" not in out:
        out["confidence"] = (1.0 if out["verified"] is True
                             else 0.0 if not ok
                             else 0.5)          # ran, unconfirmed
    if "explanation" not in out:
        out["explanation"] = (out.get("verify_reason") or out.get("error")
                              or ("done" if ok else "failed"))
    out.setdefault("proof", {k: out[k] for k in
                             ("path", "screenshot", "url", "app", "resolved", "title")
                             if out.get(k)} or None)
    return out


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

    if action in ("click", "press", "hotkey"):
        # click() and the key actions now LOOK at the screen afterwards, so use
        # what they saw rather than assuming the call returning means it worked.
        #
        # "Couldn't see" is not "didn't work". Reporting an unobservable click
        # as a failure would abort chains that were fine, on any machine
        # without mss/Pillow — so it passes with the doubt stated, and the
        # reason travels into the log and the report. Only a POSITIVE
        # observation of nothing changing is a failure.
        if result.get("verified") is True:
            return True, result.get("verify_reason", "screen responded")
        reason = result.get("verify_reason", "")
        if "can't see" in reason or "cannot tell" in reason:
            return True, reason          # honest pass: unverifiable, not failed
        if reason:
            return False, reason         # we looked, and nothing happened
        return True, "issued (not observed)"

    if action == "compose":
        # The model may have failed before a single key was pressed. That's a
        # real failure and must not be reported as done.
        if not result.get("success"):
            return False, result.get("error", "compose failed")
        composed = (result.get("composed") or "").strip()
        if not composed:
            return False, "nothing was composed"
        got = _read_focused_text()
        if got is None:
            return True, f"composed {result.get('words', 0)} words (couldn't verify)"
        # Compare on the opening words: the whole passage may be long, and
        # editors wrap/reflow, but the start is stable.
        head = " ".join(composed.lower().split())[:60]
        if head and head in " ".join(got.lower().split()):
            return True, f"composed and confirmed ({result.get('words', 0)} words)"
        return False, ("composed the text but it isn't in the focused field — "
                       "the window probably didn't have keyboard focus")

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

    # A primitive that checked for itself is the better authority — it was
    # there. open_url watches for the browser process; overriding that with a
    # blanket "assumed" was how a navigation that never happened still came
    # back verified.
    if result.get("verified") is True:
        return True, result.get("verify_reason", "confirmed by the action itself")
    if result.get("verified") is False and result.get("verify_reason"):
        return False, result["verify_reason"]

    # Nothing checked it, and there is no cheap way to. Say that, rather than
    # implying a check happened.
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
# Actions where a retry REPEATS the side effect instead of recovering from it.
#
# open_url joined this list the moment it started verifying: a retry re-runs
# webbrowser.open() and the user gets three tabs of the same page. Exactly the
# type_text duplication bug wearing a different hat — the failure was never
# "it didn't open", it was "I couldn't confirm it opened", and doing it again
# cannot answer that question.
#
# send_message is the starkest case in the list: a retry does not re-attempt a
# delivery, it makes a second delivery. Someone's phone buzzes twice. And the
# failure it would be retrying is nearly always "I couldn't confirm it sent" —
# a question another Enter cannot answer.
_NO_RETRY = {"type_text", "compose", "click", "click_text", "press", "hotkey",
             "open_url", "send_message", "ui_click"}


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


def execute_chain(steps: list, max_retries: int = 2, goal: str = "") -> dict:
    """
    Public entry point. Marks the chain as RUNNING for the duration.

    That mark is what lets a leftover Stop be told apart from a live one. Cancel
    is global on purpose — one Stop button has to halt whatever is going — but
    global also meant the flag outlived the thing it was aimed at, so a single
    press killed every command for the rest of the session. See
    control.clear_stale(); it refuses to clear while this scope is open.
    """
    try:
        from services import control
    except Exception:
        out = _execute_chain(steps, max_retries, goal)
    else:
        with control.run_scope():
            out = _execute_chain(steps, max_retries, goal)
    _learn_from_chain(goal, out)
    return out


def _learn_from_chain(goal: str, out: dict) -> None:
    """
    Record a lesson when a chat command went badly.

    Reflection was wired to workflows and projects but never to chat, which is
    how the user actually drives Jarvis — so a report after hours of use said
    `reflections: 0` and the learning loop was, in practice, dead.

    Only failures and retried runs are reflected on. A clean run teaches
    nothing, and reflect() may consult the model: on a 16 GB machine that is not
    something to do after every "open notepad". Cancels are skipped too — you
    pressing Stop is not a lesson about the task.
    """
    if not isinstance(out, dict) or out.get("cancelled"):
        return
    results = out.get("steps") or []
    ok = bool(out.get("success"))
    retried = any((s.get("attempts") or 1) > 1 for s in results if isinstance(s, dict))
    if ok and not retried:
        return

    def _bg():
        try:
            from services import reflection
            reflection.reflect(goal or "desktop command", results, ok, kind="desktop")
        except Exception:
            pass

    try:
        threading.Thread(target=_bg, daemon=True).start()
    except Exception:
        pass


def _execute_chain(steps: list, max_retries: int = 2, goal: str = "") -> dict:
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
    focus_unconfirmed = None      # set when we couldn't prove the app was in front

    # Actions that need the target app IN FRONT before they run.
    #
    # screenshot and analyze were missing from this set, and that is the whole
    # "it says there are no messages but it never opened QQ" complaint. QQ was
    # already running, so open_app saw a live window, returned verified, and
    # never raised it. The screenshot then captured whatever happened to be in
    # front — and the vision model answered honestly about the wrong window:
    # "no visible unread messages". Technically true, completely useless, and
    # indistinguishable from a real answer.
    #
    # Looking at the screen is an interaction with a specific window, exactly
    # like typing into one.
    # read_messages and ui_click focus the app themselves before they touch it,
    # so they don't strictly need this. They are here anyway because the chain's
    # focus attempt happens BEFORE the step and its failure is recorded as its
    # own result line — which is what makes "it never brought QQ up" visible in
    # the report instead of buried inside one step's error string.
    _INPUT = {"type_text", "compose", "press", "hotkey", "click", "click_text",
              "screenshot", "analyze", "scroll", "read_messages", "ui_click",
              "ui_read", "send_message"}

    # Publish the plan so it's watchable while it runs, not only afterwards.
    # ensure() defers to a caller that already published a better-worded plan.
    try:
        from services import live_plan
        live_plan.ensure(goal or "desktop task", steps, source="executor")
    except Exception:
        live_plan = None

    for i, s in enumerate(steps):
        action = (s or {}).get("action", "")
        params = (s or {}).get("params", {}) or {}

        # A step you chose to skip is not a step that failed. Recorded as
        # skipped so the plan and the report both say who decided.
        if live_plan and live_plan.should_skip(i):
            results.append({"step": i + 1, "action": action, "skipped": True,
                            "verified": True, "success": True,
                            "verify_reason": "you skipped this step"})
            live_plan.step_end(i, True, detail="skipped by you")
            continue
        if live_plan:
            live_plan.step_start(i)

        # Before ANY keyboard/mouse input, the app we opened must be foreground —
        # otherwise the input lands in the wrong window (the "notepad opens but
        # doesn't type" bug, which also happens when wait_for_window sits between
        # open and type). Confirm focus here regardless of step ordering, and
        # STOP HONESTLY if we can't get it — never type into the void.
        # read_messages can end in a screenshot when the app exposes no text,
        # and a screenshot of the wrong window is the failure this whole guard
        # exists for. It looks, so it is treated as looking.
        looking = action in ("screenshot", "analyze", "read_messages", "ui_read")
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
                time.sleep(0.5)

            # Typing has a read-back to prove it landed. LOOKING has nothing:
            # a screenshot always succeeds, and the vision model will answer
            # confidently about whatever window it was handed. So if we still
            # can't confirm the app is in front, record that — the answer must
            # carry the doubt rather than presenting a description of the wrong
            # window as the answer to a question about this one.
            if looking and not _is_foreground(last_opened):
                focus_unconfirmed = last_opened
                # A LOOK at the wrong window is the worst thing Jarvis produces,
                # because it comes back as a confident answer. The runtime report
                # of 2026-08-05 caught it exactly: focus_window failed twice for
                # 'qq', the chain carried on, and the whole request was recorded
                # as [OK] — "screen analysed". It analysed Edge.
                #
                # Typing gets to continue on an unconfirmed focus because the
                # clipboard read-back is the real arbiter. Looking has no such
                # arbiter, so it stops here instead of guessing.
                fw = focus_window(last_opened)
                if not fw.get("success"):
                    why = fw.get("error") or f"could not bring {last_opened} to the front"
                    results.append({"step": i + 1, "action": action, "success": False,
                                    "verified": False, "error": why,
                                    "focus_unconfirmed": last_opened})
                    if live_plan:
                        live_plan.step_end(i, False, error=why)
                        live_plan.finish(False, why)
                    return {"success": False, "steps": results, "failed_at": i + 1,
                            "error": why,
                            "what_to_do": ("Bring the app up yourself and ask again — "
                                           "I won't describe a window I can't confirm "
                                           "is the right one.")}

        # Pause/cancel lands BETWEEN steps. Never inside one: stopping halfway
        # through typing leaves half a sentence in the user's document.
        try:
            from services import control
            control.checkpoint(step=f"{action}")
        except Exception as c:
            if type(c).__name__ == "Cancelled":
                if live_plan:
                    live_plan.step_end(i, False, error="stopped before this step")
                    live_plan.finish(False, "you stopped it")
                return {"success": False, "steps": results, "cancelled": True,
                        "failed_at": i + 1,
                        "error": "Cancelled — stopped between steps, nothing half-done.",
                        "what_to_do": "Nothing to clean up. Ask again when ready."}
            # control unavailable is not a reason to refuse to work

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

        # An answer about the screen is only about the app we were asked about
        # if that app was actually in front. When it wasn't, say so IN the
        # answer — "no unread messages" describing the wrong window is the most
        # misleading thing Jarvis can produce, because it looks like a result.
        if action == "analyze" and focus_unconfirmed:
            caveat = (f"(I could not bring {focus_unconfirmed} to the front, so "
                      f"this describes whatever window was showing — it may not "
                      f"be {focus_unconfirmed}.)")
            for key in ("answer", "ai_answer"):
                if entry.get(key):
                    entry[key] = f"{caveat}\n\n{entry[key]}"
            entry["focus_unconfirmed"] = focus_unconfirmed

        fail = None
        if not verified:
            fail = _classify(reason or (r or {}).get("error", ""), action, r)
            entry["failure"] = fail
            # An action that RAN and didn't take is the harder failure to
            # diagnose — there's no exception, so nothing was recorded and the
            # only evidence was a one-line reason in a reply the user had
            # already scrolled past. Keep the surrounding state: which attempt,
            # how long, what the action returned, what verification looked for.
            trace.failure(
                f"desktop.{action}", reason or "action did not verify",
                detail=(f"kind={fail.get('kind')}  attempts={attempts}  "
                        f"elapsed={elapsed}s\n"
                        f"action returned: {str(r)[:400]}"),
                # One dict, splatted once: a params key called "goal" or
                # "target" would otherwise be a TypeError inside error handling,
                # which is the worst possible place for a new exception.
                **{"step": i + 1, "goal": goal, "target": target,
                   **(params or {})})
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

        if live_plan:
            live_plan.step_end(i, verified,
                               detail=(reason if verified else ""),
                               error=("" if verified else (fail or {}).get("cause", reason)),
                               failure=fail)

        if not verified:
            # Report the CAUSE and the FIX, not just the symptom.
            if live_plan:
                live_plan.finish(False, fail["cause"])
            try:
                from services import selfeval
                selfeval.evaluate(goal or "desktop task", results, False)
            except Exception:
                pass
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
    if live_plan:
        live_plan.finish(True)
    # Score the run against real evidence and record one concrete adjustment for
    # next time. Never blocks the reply — see services/selfeval.py.
    try:
        from services import selfeval
        selfeval.evaluate(goal or "desktop task", results, True)
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


def open_url(url: str, browser: str = "", query: str = "") -> dict:
    """
    Open a URL, in a SPECIFIC browser when one is named.

    webbrowser.open() uses the OS default, which is not necessarily the browser
    the user asked for or even one that is installed. Naming the executable
    means "open browser and search X" lands in the browser Jarvis actually
    resolved rather than whatever Windows happens to be configured with.

    WHERE THE URL IS ALLOWED TO POINT. This is the path that opens the user's
    REAL browser — the everyday one, signed in to everything — so it needs the
    same check as the Playwright one, and it is the one that actually runs:
    "go to <x>" is resolved by decompose into open_url long before the chat
    adapter's browser branch is reached. A review that only looked at the
    adapter would leave this door open.

    Two things specific to this door and not the other:
      - `webbrowser.open` will happily open file:// — the whole local disk.
      - a "URL" starting with "-" becomes a command-line FLAG to the browser
        executable in the Popen call below, not an address.
    """
    if not url:
        return {"success": False, "action": "open_url", "error": "no URL"}
    if url.startswith("-"):
        return {"success": False, "action": "open_url",
                "error": "that starts with '-', so the browser would read it as "
                         "a command-line option rather than an address"}
    from agents.browser_agent import check_url
    url, why = check_url(url)
    if why:
        return {"success": False, "action": "open_url", "error": why, "blocked": True}
    exe = None
    if browser:
        try:
            from services.app_resolver import resolve as _resolve_app
            exe = _resolve_app(browser)
        except Exception:
            exe = None
    try:
        if exe:
            subprocess.Popen([exe, url], shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import webbrowser
            webbrowser.open(url)

        # VERIFY WHAT IS ACTUALLY VERIFIABLE HERE, and be explicit about what
        # isn't. This used to sleep 2s and return success unconditionally: a
        # browser that never launched, a dead profile, a crash on start — all
        # came back as "opened it ✓". Three separate reviews called this out
        # and all three were right.
        #
        # What we CAN observe: a browser process exists and its window came to
        # the front. What we CANNOT observe: the page content — this is the
        # SYSTEM browser, launched by handle-less Popen/webbrowser, so there is
        # no DOM to read. Saying so is the honest half; pretending otherwise is
        # what made this an issue. When content matters the chain follows with
        # screenshot+analyze, which IS the content check.
        from services.tool_registry import default_browser
        target = browser or default_browser()
        appeared = False
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if _running_process_for(target):
                appeared = True
                break
            time.sleep(0.25)

        if not appeared:
            # NOT a hard failure. webbrowser.open() may have launched something
            # whose process name we don't map, and calling that "the browser
            # never started" would break a working setup to satisfy a check.
            # success=True because the request was made; verified=False because
            # we could not confirm it, which is precisely the distinction the
            # contract exists to carry.
            return {"success": True, "verified": False, "action": "open_url",
                    "url": url, "browser": browser or "system default",
                    "verify_reason": (f"asked {target} to open the page but never saw "
                                      f"a {target} process — it may have failed to "
                                      f"start, or it runs under a name Jarvis "
                                      f"doesn't recognise"),
                    **({"query": query} if query else {})}

        focus_window(target)
        time.sleep(1.2)          # let the page paint before anyone screenshots it
        front = _is_foreground(target)
        # Verified on the PROCESS, not the foreground check. The process check
        # is reliable; foreground is not, and hanging the verdict on the flakier
        # of the two signals would fail navigations that plainly worked.
        return {"success": True, "verified": True, "action": "open_url",
                "url": url, "browser": browser or "system default",
                "verify_reason": (
                    f"{target} is running and in front — page CONTENT not checked, "
                    f"Jarvis has no handle on the system browser"
                    if front else
                    f"{target} is running but isn't in front; the page may be "
                    f"behind another window"),
                **({"query": query} if query else {})}
    except Exception as e:
        return {"success": False, "verified": False, "action": "open_url",
                "url": url, "error": str(e)}


def close_window(title_contains: str) -> dict:
    """Close a window whose title contains the given string."""
    if not HAS_WINDOWS:
        # Fallback: Alt+F4 on focused window
        return hotkey("alt", "f4")
    try:
        # The caller names a specific window to close/minimise/maximise;
        # there is no app to resolve. Focus and launch, which DO take an
        # app name, go through process matching instead.
        # nosemgrep: jarvis-window-matched-by-title
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return {"success": False, "error": f"No window with '{title_contains}'"}
        wins[0].close()
        return {"success": True, "action": "close_window", "title": title_contains}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _process_names_for(app: str) -> set:
    """
    Executable names a window for this app might belong to.

    Window titles are LOCALISED; executable names are not. On a Chinese Windows
    install Notepad's title is "无标题 - 记事本", which contains no "notepad" at
    all — so every title-based lookup failed and focus_window reported "No
    window with 'notepad'" on literally every run. The process is still
    notepad.exe in any language, so that's what we match on.
    """
    a = (app or "").strip().lower()
    if not a:
        return set()
    names = {a, f"{a}.exe", a.replace(" ", ""), f"{a.replace(' ', '')}.exe"}
    # Whatever app_resolver actually launched is the most reliable answer.
    try:
        from services.app_resolver import get_cached
        real = get_cached(a)
        if real:
            names.add(os.path.basename(real).lower())
    except Exception:
        pass
    ALIASES = {
        "chrome": {"chrome.exe"}, "edge": {"msedge.exe"}, "msedge": {"msedge.exe"},
        "firefox": {"firefox.exe"}, "explorer": {"explorer.exe"},
        "files": {"explorer.exe"}, "calculator": {"calculatorapp.exe", "calc.exe"},
        "calc": {"calculatorapp.exe", "calc.exe"},
        "vscode": {"code.exe"}, "code": {"code.exe"},
        "word": {"winword.exe"}, "excel": {"excel.exe"},
        "terminal": {"cmd.exe", "windowsterminal.exe"},
        "wechat": {"wechat.exe", "weixin.exe"},
        "qq": {"qq.exe"}, "doubao": {"doubao.exe"},
    }
    names |= ALIASES.get(a, set())
    return {n for n in names if n}


def _win32_focus(title_contains: str) -> bool:
    """
    Bring a window to the front using the Win32 API directly (ctypes — no new
    dependency). pygetwindow's .activate() fails on modern Windows because the
    OS refuses SetForegroundWindow from a process that doesn't own the current
    foreground window. The accepted workaround is to attach our input queue to
    the foreground thread first, which is what this does. This is the fix for
    the live "opened notepad but couldn't bring it to the foreground" failure.

    Windows are matched by TITLE or by OWNING PROCESS — see _process_names_for.
    Title-only matching silently fails on any non-English Windows.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32

        target = {"hwnd": None, "by": None}
        # A window hidden in the SYSTEM TRAY, kept as a weaker candidate.
        #
        # This is the "check my QQ messages" bug, finally. QQ and WeChat close
        # to the tray rather than exiting: the process keeps running and its
        # main window becomes INVISIBLE. open_app then sees the process and
        # says "already running, verified"; focus_window enumerated only
        # visible windows and said "no window found for 'qq'" — and the chain
        # screenshotted whatever was in front and answered confidently about
        # the wrong app. The two calls disagreed because they were asking
        # different questions: "is the process alive" and "is a window shown".
        #
        # A tray window is still a real HWND and ShowWindow(SW_RESTORE) brings
        # it back. We were skipping it before ever trying.
        tray = {"hwnd": None}
        needle = (title_contains or "").lower()
        want_procs = _process_names_for(title_contains)

        def _proc_name(hwnd):
            try:
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value:
                    return ""
                return (psutil.Process(pid.value).name() or "").lower()
            except Exception:
                return ""

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _):
            n = u32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True            # no title = tool window, not ours
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            titled = bool(needle) and needle in buf.value.lower()
            owned = bool(want_procs) and _proc_name(hwnd) in want_procs
            if not (titled or owned):
                return True
            if not u32.IsWindowVisible(hwnd):
                # Titled, ours, and hidden — that is what living in the tray
                # looks like. Remembered rather than taken, so a genuinely
                # visible window always wins.
                if owned and tray["hwnd"] is None:
                    tray["hwnd"] = hwnd
                return True
            if titled:
                target["hwnd"], target["by"] = hwnd, "title"
                return False           # exact-ish title match wins outright
            target["hwnd"], target["by"] = hwnd, "process"
            return True                # keep looking for a title match

        u32.EnumWindows(_enum, 0)
        hwnd = target["hwnd"]
        if not hwnd and tray["hwnd"]:
            hwnd = tray["hwnd"]
            target["by"] = "tray"
            u32.ShowWindow(hwnd, 9)    # SW_RESTORE — un-hide it before focusing
            time.sleep(0.25)
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


def _window_titled(name: str) -> bool:
    """Is there any VISIBLE window whose title mentions this? Never raises."""
    if not HAS_WINDOWS or not name:
        return False
    try:
        return any(w.title and name.lower() in w.title.lower() for w in gw.getAllWindows())
    except Exception:
        return False


def focus_window(title_contains: str) -> dict:
    """Bring a window to the foreground, robustly, and CONFIRM it worked."""
    # Try the real Win32 path FIRST — it's the one that actually works on Windows.
    if _win32_focus(title_contains):
        return {"success": True, "action": "focus_window", "title": title_contains,
                "confirmed": True, "method": "win32"}

    # Checked BEFORE the pygetwindow guard. The tray explanation is the most
    # useful thing we can say about this failure and it must not depend on
    # which optional package happens to be importable.
    running = _running_process_for(title_contains)
    if running and not _window_titled(title_contains):
        return {"success": False, "tray_suspected": True,
                "error": f"{title_contains} is running as {running}, but it has no "
                         f"window on screen — it is almost certainly minimised to "
                         f"the system tray (bottom-right, by the clock). Click it "
                         f"there once, then ask me again."}
    if not HAS_WINDOWS:
        return {"success": False, "error": "pygetwindow not available"}
    try:
        # getWindowsWithTitle is case-SENSITIVE and title-only, so it misses
        # "Untitled - Notepad" for "notepad" and misses localised titles
        # entirely. Do our own case-insensitive scan, then fall back to
        # matching the owning process by geometry-free title comparison.
        wins = [w for w in gw.getAllWindows()
                if w.title and title_contains.lower() in w.title.lower()]
        if not wins:
            return {"success": False,
                    "error": f"No window found for '{title_contains}' "
                             f"(checked window titles and running processes)"}
        win = wins[0]
        for _attempt in range(3):
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
    """
    Is a window for this app currently the active/foreground window?

    Checks the owning process as well as the title, for the same reason
    _win32_focus does: window titles are localised and an English app name will
    never appear in "无标题 - 记事本".
    """
    needle = (title_contains or "").lower()
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.windll.user32
            hwnd = u32.GetForegroundWindow()
            if hwnd:
                n = u32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                if needle and needle in buf.value.lower():
                    return True
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pname = (psutil.Process(pid.value).name() or "").lower()
                    if pname in _process_names_for(title_contains):
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
        # The caller names a specific window to close/minimise/maximise;
        # there is no app to resolve. Focus and launch, which DO take an
        # app name, go through process matching instead.
        # nosemgrep: jarvis-window-matched-by-title
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
        # The caller names a specific window to close/minimise/maximise;
        # there is no app to resolve. Focus and launch, which DO take an
        # app name, go through process matching instead.
        # nosemgrep: jarvis-window-matched-by-title
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
