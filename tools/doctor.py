"""
tools/doctor.py - "why won't it start?", answered in ten seconds.

The existing diagnostics live inside the backend, which is useless when the
backend is the thing that won't come up. This runs standalone: no server, no
FastAPI, no database. Plain Python, works from any directory, on any drive.

It checks the things that have ACTUALLY gone wrong on this project, not a
generic dependency list - including several that produce error messages
pointing at the wrong culprit entirely:

  * .bat files with Unix line endings. cmd.exe loses its place and eats the
    start of lines, so you get "'tle' is not recognized" and a launcher that
    claims Python isn't installed when it plainly is.
  * a stray package.json at the repo root (from `npm init -y` in the wrong
    folder), which makes `npm run dev` start the wrong project.
  * `playwright install chrome` vs `chromium` - the first ignores the China
    mirror and can never succeed behind the GFW.
  * ports already held by a dev server from a previous run.

Run it:  python tools/doctor.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

OK, WARN, BAD = "ok", "warn", "BAD"
_rows = []


def add(status, what, detail, fix=""):
    _rows.append((status, what, detail, fix))


def _run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr or "").strip()
    except Exception:
        return ""


# ── 1. Am I even looking at the right folder? ────────────────────────────────

def check_layout():
    if not BACKEND.is_dir():
        add(BAD, "Project layout", f"no backend/ under {ROOT}",
            "You're running this from outside the Jarvis folder. cd to it first.")
        return
    add(OK, "Project layout", f"{ROOT}")

    if not (BACKEND / "main.py").is_file():
        add(BAD, "backend/main.py", "missing", "Re-clone or re-download the project.")
    if not (FRONTEND / "package.json").is_file():
        add(BAD, "frontend/package.json", "missing", "Re-clone or re-download the project.")

    # The classic: `npm init -y` run at the repo root by mistake.
    stray = ROOT / "package.json"
    if stray.is_file():
        try:
            name = json.loads(stray.read_text(encoding="utf-8")).get("name", "?")
        except Exception:
            name = "?"
        add(BAD, "Stray package.json at root", f'name="{name}" - this is NOT the UI',
            f'The UI lives in frontend/. Delete these THREE from {ROOT}:\n'
            f'          del package.json package-lock.json\n'
            f'          rmdir /s /q node_modules\n'
            f'      then:  cd frontend  &&  npm install  &&  npm run dev')
    if (ROOT / "node_modules").is_dir() and not stray.is_file():
        add(WARN, "node_modules at root", "leftover from an npm command in the wrong folder",
            f"rmdir /s /q {ROOT / 'node_modules'}")


# ── 2. Line endings - the one that produces lying error messages ─────────────

def check_line_endings():
    bad = []
    for bat in sorted(ROOT.glob("*.bat")):
        try:
            data = bat.read_bytes()
        except OSError:
            continue
        if b"\n" in data and b"\r\n" not in data:
            bad.append(bat.name)
    if bad:
        add(BAD, "Batch file line endings", f"Unix (LF) in: {', '.join(bad)}",
            "This is why the launcher printed nonsense like \"'tle' is not\n"
            "      recognized\" and claimed Python was missing. cmd.exe needs CRLF.\n"
            "      Fix:  git config core.autocrlf true  &&  git checkout -- *.bat\n"
            "      Or in PowerShell, per file:\n"
            "          (Get-Content x.bat -Raw) -replace \"`r`n\",\"`n\" -replace \"`n\",\"`r`n\" |\n"
            "              Set-Content x.bat -NoNewline")
    elif list(ROOT.glob("*.bat")):
        add(OK, "Batch file line endings", "CRLF - cmd.exe will parse these correctly")


# ── 3. Python and its packages ───────────────────────────────────────────────

def check_python():
    v = sys.version_info
    label = f"{v.major}.{v.minor}.{v.micro} at {sys.executable}"
    if v < (3, 10):
        add(BAD, "Python", label, "Jarvis needs 3.10+. Install 3.11 from python.org.")
    else:
        add(OK, "Python", label)

    req = BACKEND / "requirements.txt"
    if not req.is_file():
        add(WARN, "requirements.txt", "not found in backend/")
        return

    # import name -> what breaks without it
    NEEDED = {
        "fastapi": "the backend won't start at all",
        "uvicorn": "the backend won't start at all",
        "pydantic": "the backend won't start at all",
        "dotenv": "the backend won't start at all",
        "psutil": "no system stats, and Phase 0 can't run",
        "requests": "no job scanning",
        "bs4": "no job scanning",
        "playwright": "no freelance login or bidding",
        "ollama": "no local AI",
        "pyautogui": "no desktop control (mouse/keyboard)",
        "pygetwindow": "no window focus - typing lands in the wrong window",
        "pyperclip": "typing verification is skipped",
        "PIL": "no screenshots",
        "mss": "slow screenshots",
        "pytesseract": "no reading text off the screen",
        "cv2": "no finding things on screen by image",
        "cryptography": "the encrypted credential vault won't open",
    }
    missing = []
    for mod, why in NEEDED.items():
        try:
            __import__(mod)
        except BaseException:
            # BaseException on purpose: a half-broken native wheel can raise a
            # pyo3 PanicException, which is not an Exception subclass.
            missing.append((mod, why))
    if missing:
        add(BAD, "Python packages", f"{len(missing)} missing: "
            + ", ".join(m for m, _ in missing),
            f"cd /d {BACKEND}  &&  python -m pip install -r requirements.txt\n"
            + "\n".join(f"          {m:<14} missing -> {w}" for m, w in missing))
    else:
        add(OK, "Python packages", f"all {len(NEEDED)} present")


# ── 4. Node ──────────────────────────────────────────────────────────────────

def check_node():
    node = shutil.which("node")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not node:
        add(BAD, "Node.js", "not on PATH", "Install Node.js LTS from nodejs.org.")
    else:
        add(OK, "Node.js", _run([node, "-v"]) or node)
    if not npm:
        add(BAD, "npm", "not on PATH", "Comes with Node.js - reinstall it.")
    else:
        add(OK, "npm", _run([npm, "-v"], timeout=20) or npm)

    if FRONTEND.is_dir() and not (FRONTEND / "node_modules").is_dir():
        add(WARN, "UI packages", "frontend/node_modules missing",
            f"cd /d {FRONTEND}  &&  npm install")
    elif FRONTEND.is_dir():
        add(OK, "UI packages", "frontend/node_modules present")


# ── 5. Ollama ────────────────────────────────────────────────────────────────

def check_ollama():
    host = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        import urllib.request
        with urllib.request.urlopen(f"{host}/api/tags", timeout=4) as r:
            data = json.loads(r.read().decode())
        names = [m.get("name") or m.get("model") for m in data.get("models", [])]
    except Exception as e:
        add(BAD, "Ollama", f"not answering on {host} ({str(e)[:40]})",
            "Open a new terminal and run:  ollama serve")
        return
    if not names:
        add(BAD, "Ollama models", "running, but no models installed",
            "ollama pull qwen2.5:3b        (thinking)\n"
            "          ollama pull llava:7b          (understanding the screen)")
        return

    add(OK, "Ollama", f"{len(names)} model(s): {', '.join(names[:4])}")
    tiny = [n for n in names if any(t in n for t in (":0.5b", ":1b", "0_5b"))]
    big = [n for n in names if not any(t in n for t in (":0.5b", ":1b", "0_5b"))]
    if tiny and not big:
        add(WARN, "Model size", f"only tiny models: {', '.join(tiny)}",
            "Under ~1B parameters can't follow multi-step instructions - this is\n"
            "      the single biggest reason Jarvis feels stupid.\n"
            "          ollama pull qwen2.5:3b")
    if not any("llava" in n or "vision" in n or "minicpm-v" in n for n in names):
        add(WARN, "Vision model", "none installed",
            "Screen understanding falls back to plain OCR.\n"
            "          ollama pull llava:7b")


# ── 6. Playwright browser ────────────────────────────────────────────────────

def check_playwright():
    try:
        import playwright  # noqa: F401
    except ImportError:
        add(BAD, "Playwright", "package not installed",
            "pip install playwright")
        return
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expandvars(
        r"%LOCALAPPDATA%\ms-playwright" if os.name == "nt" else "~/.cache/ms-playwright")
    root = Path(os.path.expanduser(root))
    have = root.is_dir() and any(p.name.startswith("chromium") for p in root.iterdir())
    if have:
        add(OK, "Automation browser", f"chromium present in {root}")
    else:
        add(BAD, "Automation browser", "chromium not downloaded",
            'set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright\n'
            "          python -m playwright install chromium\n"
            '      NOTE: use "chromium", NOT "chrome". `playwright install chrome`\n'
            "      fetches Google's MSI directly and ignores the mirror, so from\n"
            "      China it always fails with \"unable to connect to remote server\".")


# ── 7. Tesseract ─────────────────────────────────────────────────────────────

def check_tesseract():
    exe = shutil.which("tesseract")
    if exe:
        add(OK, "Tesseract OCR", (_run([exe, "--version"]).splitlines() or ["?"])[0])
    else:
        add(WARN, "Tesseract OCR", "not on PATH",
            "Only needed to read text off the screen. Install from\n"
            "      github.com/UB-Mannheim/tesseract/wiki and tick 'Add to PATH'.")


# ── 8. Ports ─────────────────────────────────────────────────────────────────

def check_ports():
    busy = []
    for port, who in ((8000, "backend"), (5173, "UI"), (11434, "Ollama")):
        s = socket.socket()
        s.settimeout(0.4)
        try:
            s.connect(("127.0.0.1", port))
            busy.append((port, who))
        except Exception:
            pass
        finally:
            s.close()
    inuse = {p for p, _ in busy}
    if 11434 in inuse:
        add(OK, "Port 11434", "Ollama is listening")
    if 8000 in inuse:
        add(WARN, "Port 8000", "already in use",
            "A backend may already be running - check your open terminals before\n"
            "      starting another. If it's stale:  taskkill /f /im python.exe")
    if 5173 in inuse:
        add(WARN, "Port 5173", "already in use",
            "Vite will fall back to 5174/5175. That now works (CORS allows any\n"
            "      localhost port), but a stale dev server may serve the WRONG\n"
            "      project. To clear:  taskkill /f /im node.exe")


def main():
    print("=" * 74)
    print("JARVIS DOCTOR - why won't it start?")
    print(f"looking at: {ROOT}")
    print("=" * 74)

    for fn in (check_layout, check_line_endings, check_python, check_node,
               check_ollama, check_playwright, check_tesseract, check_ports):
        try:
            fn()
        except Exception as e:
            add(WARN, fn.__name__, f"check itself failed: {str(e)[:60]}")

    bad = [r for r in _rows if r[0] == BAD]
    warn = [r for r in _rows if r[0] == WARN]

    print()
    for status, what, detail, _ in _rows:
        mark = {OK: "[ ok ]", WARN: "[warn]", BAD: "[STOP]"}[status]
        print(f"  {mark} {what:<28} {detail}")

    if bad or warn:
        print("\n" + "=" * 74)
        print("  WHAT TO DO, IN ORDER")
        print("=" * 74)
        for i, (status, what, _, fix) in enumerate(bad + warn, 1):
            if not fix:
                continue
            tag = "MUST FIX" if status == BAD else "optional"
            print(f"\n  {i}. [{tag}] {what}")
            for line in fix.splitlines():
                print(f"      {line}")

    print("\n" + "=" * 74)
    if bad:
        print(f"  {len(bad)} thing(s) will stop Jarvis starting. Fix those first.")
    elif warn:
        print("  Nothing blocking. The warnings above limit what Jarvis can do.")
        print("  Next:  START_JARVIS.bat")
    else:
        print("  Everything checks out. Next:  START_JARVIS.bat")
    print("=" * 74)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
