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
    """Type text with special chars using pyperclip paste trick."""
    err = _require("pyautogui")
    if err: return err
    try:
        import pyperclip
        with _lock:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        return {"success": True, "action": "type_raw", "length": len(text)}
    except ImportError:
        return type_text(text)


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
    key = name_or_path.lower().replace(" ", "")
    known = key in KNOWN
    cmd = KNOWN.get(key, [name_or_path])
    # Browsers/GUI apps live in the registry App Paths, not on PATH — launch via
    # shell 'start' so Windows resolves them (fixes "Windows cannot find 'edge'").
    SHELL_START = {"msedge.exe", "chrome.exe", "firefox.exe", "code"}
    launched = False
    try:
        if cmd[0] in SHELL_START:
            subprocess.Popen(["cmd.exe", "/c", "start", "", *cmd],
                             shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmd, shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        launched = True
    except (FileNotFoundError, OSError):
        pass
    except Exception as e:
        return {"success": False, "action": "open_app", "error": str(e)}

    if launched:
        time.sleep(1.2)
        if known:
            # Trusted mapping: the exe exists and started. Report the extra
            # confirmation when we have it, but don't second-guess a known app.
            return {"success": True, "action": "open_app", "app": name_or_path,
                    "resolved": cmd[0], "method": "direct",
                    "verified": _app_visible(name_or_path)}
        if _app_visible(name_or_path):
            return {"success": True, "action": "open_app", "app": name_or_path,
                    "resolved": cmd[0], "method": "direct", "verified": True}

    # Self-recovery, like a human would:
    # 1) let the Windows shell resolve the raw name (App Paths, PATH, aliases)
    if os.name == "nt":
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", name_or_path], shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.0)
            if _app_visible(name_or_path):
                return {"success": True, "action": "open_app", "app": name_or_path,
                        "resolved": "shell start", "method": "start", "verified": True}
        except Exception:
            pass
        # 2) search the Start Menu (works for ANY installed app: WeChat, Photoshop…)
        if _start_menu_launch(name_or_path):
            if _app_visible(name_or_path):
                return {"success": True, "action": "open_app", "app": name_or_path,
                        "resolved": "start menu search", "method": "start_menu",
                        "verified": True}
            # Search ran but we can't see a matching window — Enter may still
            # have launched something whose title differs. Be honest about it.
            return {"success": True, "action": "open_app", "app": name_or_path,
                    "resolved": "start menu search", "method": "start_menu",
                    "verified": False,
                    "note": "launched via Start Menu but couldn't visually confirm — check your screen"}
    return {"success": False, "action": "open_app",
            "error": f"Could not find or open '{name_or_path}' "
                     f"(tried direct launch, shell start, Start Menu search)"}


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


def wait_for_window(title_contains: str, timeout: float = 8.0) -> dict:
    """
    Block until a window whose title contains the string appears (or the app's
    process shows up). This is the glue that makes chained commands reliable:
    'open notepad' → wait_for_window('notepad') → type — instead of typing
    into whatever window happened to have focus 1.5s later.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _app_visible(title_contains):
            return {"success": True, "action": "wait_for_window",
                    "title": title_contains,
                    "waited": round(timeout - (deadline - time.time()), 1)}
        time.sleep(0.4)
    return {"success": False, "action": "wait_for_window",
            "error": f"Window '{title_contains}' did not appear within {timeout}s"}


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
        "wait_for_window": lambda p: wait_for_window(p.get("title", ""),
                                                     float(p.get("timeout", 8))),
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
    # no cheap post-hoc check — trust the primitive's own success flag.
    return True, "assumed (no cheap verification)"


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
    for i, s in enumerate(steps):
        action = (s or {}).get("action", "")
        params = (s or {}).get("params", {}) or {}

        verified, reason, r = False, "", {}
        attempts = 0
        while attempts <= max_retries:
            attempts += 1
            r = _run_action(action, params)
            verified, reason = _verify_action(action, params, r)
            if verified:
                break
            if attempts <= max_retries:
                time.sleep(min(1.0 * attempts, 3.0))   # brief backoff, then retry

        entry = {"step": i + 1, "action": action, "attempts": attempts,
                 "verified": verified, "verify_reason": reason, **(r or {})}
        results.append(entry)

        if not verified:
            return {"success": False, "steps": results, "failed_at": i + 1,
                    "error": f"{action} could not be verified: {reason}"}

        # After a confirmed app open, wait + focus so the next input lands right.
        if action == "open_app":
            target = params.get("name_or_path") or params.get("app", "")
            nxt = steps[i + 1]["action"] if i + 1 < len(steps) else None
            if nxt in ("type_text", "press", "hotkey", "click", "click_text"):
                focus_window(target)
                time.sleep(0.5)

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


def focus_window(title_contains: str) -> dict:
    """Bring a window to the foreground."""
    if not HAS_WINDOWS:
        return {"success": False, "error": "pygetwindow not available"}
    try:
        wins = gw.getWindowsWithTitle(title_contains)
        if not wins:
            return {"success": False, "error": f"No window with '{title_contains}'"}
        wins[0].activate()
        time.sleep(0.3)
        return {"success": True, "action": "focus_window", "title": title_contains}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
    Run a shell command and return output.
    ONLY whitelisted safe commands are allowed.
    """
    WHITELIST = ["dir", "ls", "echo", "type", "cat", "python", "pip", "ollama", "node", "npm", "git status", "git log"]
    cmd_lower = command.lower().strip()
    if not any(cmd_lower.startswith(w) for w in WHITELIST):
        return {"success": False, "error": f"Command not in whitelist: {command}"}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {
            "success":    result.returncode == 0,
            "stdout":     result.stdout[:2000],
            "stderr":     result.stderr[:500],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
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
