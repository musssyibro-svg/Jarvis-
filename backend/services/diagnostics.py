"""
services/diagnostics.py — full-system diagnosis + a downloadable runtime report.

Two jobs:

1. deep_check(): answer "what is missing on THIS machine, and what do I type to
   fix it?" Every Python package, external binary, model and permission Jarvis
   depends on, each with a concrete install command. This is what turns "it
   silently doesn't work" into a checklist.

2. build_report(): bundle everything a human (or another AI) needs to debug a
   bad run into ONE text file: the diagnosis, live OS state, recent execution
   traces, recent activity feed, the log tail, and environment info. Downloaded
   from the Diagnostics screen so nothing has to be copied out of terminals.
"""
import io
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

# name -> (import_name, why it matters, pip install target)
PY_PACKAGES = [
    ("fastapi",        "fastapi",      "web backend",                    "fastapi"),
    ("uvicorn",        "uvicorn",      "runs the backend server",        "uvicorn[standard]"),
    ("pyautogui",      "pyautogui",    "mouse + keyboard control",       "pyautogui"),
    ("pygetwindow",    "pygetwindow",  "window focus / detection",       "pygetwindow"),
    ("pyperclip",      "pyperclip",    "clipboard (verifies typing)",    "pyperclip"),
    ("mss",            "mss",          "fast screenshots",               "mss"),
    ("Pillow",         "PIL",          "image handling for vision",      "Pillow"),
    ("pytesseract",    "pytesseract",  "OCR text extraction",            "pytesseract"),
    ("opencv-python",  "cv2",          "image matching on screen",       "opencv-python"),
    ("psutil",         "psutil",       "system + process info",          "psutil"),
    ("playwright",     "playwright",   "browser automation (freelance)", "playwright"),
    ("ollama",         "ollama",       "local LLM client",               "ollama"),
    ("cryptography",   "cryptography", "encrypted credential vault",     "cryptography"),
    ("requests",       "requests",     "http calls",                     "requests"),
    ("beautifulsoup4", "bs4",          "job scraping",                   "beautifulsoup4"),
    ("schedule",       "schedule",     "scheduled runs",                 "schedule"),
    ("pypdf",          "pypdf",        "reading PDFs into the Brain",    "pypdf"),
]

WINDOWS_ONLY = {"pygetwindow"}


def _cfg(key: str, default: str) -> str:
    """Setting > environment > default — the same order the running code uses."""
    try:
        from services import config
        return config.get(key, default) or default
    except Exception:
        return default

# Playwright's browser download goes to a Google-hosted CDN, which is not
# reachable from mainland China. Quoting the bare command sends people into a
# ten-minute hang; the mirror line is the difference between working and not.
_PW_FIX = ("set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright "
           "&& python -m playwright install chromium   "
           "(drop the first part outside China)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_packages() -> list[dict]:
    out = []
    for name, mod, why, pip_target in PY_PACKAGES:
        if name in WINDOWS_ONLY and os.name != "nt":
            continue
        try:
            __import__(mod)
            ok, detail = True, "installed"
        except BaseException as e:   # BaseException: broken native wheels can panic
            ok, detail = False, f"missing/broken ({type(e).__name__})"
        out.append({"group": "Python package", "name": name, "ok": ok,
                    "detail": detail, "why": why,
                    "fix": None if ok else f"pip install {pip_target}"})
    return out


def _check_binaries() -> list[dict]:
    checks = []

    # Tesseract: pip package can import while the BINARY is absent.
    tpath = shutil.which("tesseract")
    if not tpath and os.name == "nt":
        for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                     r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                     os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")):
            if os.path.exists(cand):
                tpath = cand
                break
    checks.append({"group": "Binary", "name": "Tesseract OCR", "ok": bool(tpath),
                   "detail": tpath or "not found",
                   "why": "reads text off the screen",
                   "fix": None if tpath else
                          "Install from github.com/UB-Mannheim/tesseract/wiki (Windows installer)"})

    # Node/npm — needed for the UI.
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    checks.append({"group": "Binary", "name": "Node / npm", "ok": bool(npm),
                   "detail": npm or "not found",
                   "why": "runs the Jarvis UI",
                   "fix": None if npm else "Install Node.js LTS from nodejs.org"})

    # Playwright browser binaries (separate from the pip package).
    try:
        import playwright  # noqa: F401
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expandvars(
            r"%LOCALAPPDATA%\ms-playwright" if os.name == "nt" else "~/.cache/ms-playwright")
        has = os.path.isdir(os.path.expanduser(root)) and bool(os.listdir(os.path.expanduser(root)))
        checks.append({"group": "Binary", "name": "Playwright browsers", "ok": has,
                       "detail": root if has else "browser binaries not installed",
                       "why": "logging in + submitting on freelance sites",
                       "fix": None if has else _PW_FIX})
    except Exception:
        checks.append({"group": "Binary", "name": "Playwright browsers", "ok": False,
                       "detail": "playwright package missing",
                       "why": "logging in + submitting on freelance sites",
                       "fix": "pip install playwright  then  " + _PW_FIX})
    return checks


def _check_ollama_models() -> list[dict]:
    out = []
    try:
        import requests
        url = _cfg("ollama_url", "http://127.0.0.1:11434")
        r = requests.get(f"{url}/api/tags", timeout=3)
        models = [m.get("name", "") for m in r.json().get("models", [])]
        out.append({"group": "Ollama", "name": "Ollama server", "ok": True,
                    "detail": f"running · {len(models)} model(s)",
                    "why": "all local AI", "fix": None})
        wanted = [
            # Read through config, NOT os.getenv. Reading the env var here is
            # why Diagnostics kept reporting "you haven't set this" straight
            # after the user set it in Settings and saved: the row went to the
            # database, this looked at an environment variable nobody had set,
            # and the two never met.
            ("fast chat/proposals", _cfg("ollama_fast_model", "qwen2.5:3b"), "qwen2.5:3b"),
            ("reasoning/planning",  _cfg("ollama_reasoning_model", "deepseek-r1:1.5b"), "deepseek-r1:1.5b"),
            ("vision (screen)",     _cfg("ollama_vision_model", "llava:7b"), "llava:7b"),
        ]
        for role, want, pull in wanted:
            base = want.split(":")[0]
            ok = any(m == want or m.split(":")[0] == base for m in models)
            out.append({"group": "Ollama", "name": f"Model — {role}", "ok": ok,
                        "detail": want if ok else f"{want} not installed",
                        "why": "quality + speed of that feature",
                        "fix": None if ok else f"ollama pull {pull}"})

        # Is the model actually in use big enough to be useful? A 0.5B model
        # cannot reliably follow multi-constraint prompts — it's the single
        # biggest reason Jarvis "feels dumb" even when the plumbing is correct.
        # Ask the ROUTER, which is what actually answers requests, not the
        # configured preference. These two disagreed in a real report — the
        # diagnosis said "in use: qwen2.5:3b" while the live state said the
        # fast model was qwen2.5:0.5b — and a report that contradicts itself
        # is worse than one that admits it doesn't know.
        active, free_ram, why_small = "", None, ""
        try:
            from services import model_router
            chosen = model_router.pick("chat")
            active = chosen.get("model") or ""
            free_ram = chosen.get("free_ram_gb")
            why_small = chosen.get("warning") or ""
        except Exception:
            try:
                from services.ollama_manager import resolve_models
                active = (resolve_models().get("resolved") or {}).get("fast") or ""
            except Exception:
                active = ""
        size = _param_size(active)
        too_small = size is not None and size < 1.0

        # Is something better already installed? If so, RAM is the problem, not
        # a missing download, and the fix is completely different.
        better = ""
        if too_small:
            try:
                from services.os_state import _better_installed
                better = _better_installed(models)
            except Exception:
                pass

        if not too_small:
            detail = active or "unknown"
            fix = None
        elif better:
            detail = (f"{active} (~{size}B) is answering, even though {better} is "
                      f"installed — only {free_ram}GB of RAM is free, and the "
                      f"bigger model doesn't fit.")
            fix = "close some apps to free RAM; Jarvis switches back on its own"
        else:
            detail = (f"{active} — about {size}B parameters. Too small to follow "
                      f"detailed instructions reliably.")
            fix = "ollama pull qwen2.5:3b"

        out.append({
            "group": "Ollama", "name": "Model actually answering", "ok": not too_small,
            "detail": detail,
            "why": "how smart Jarvis's answers and proposals are",
            "fix": fix,
        })
        if why_small and too_small:
            out.append({"group": "Ollama", "name": "Why that model",
                        "ok": True, "detail": why_small,
                        "why": "the router picks what fits in free RAM", "fix": None})
    except Exception as e:
        out.append({"group": "Ollama", "name": "Ollama server", "ok": False,
                    "detail": f"not reachable ({type(e).__name__})",
                    "why": "all local AI",
                    "fix": "Start it: ollama serve   (install from ollama.com)"})
    return out


def _param_size(model: str) -> float | None:
    """Parameter count in billions parsed from an Ollama tag ('qwen2.5:0.5b' -> 0.5)."""
    import re
    m = re.search(r"[:\-](\d+(?:\.\d+)?)\s*b\b", (model or "").lower())
    return float(m.group(1)) if m else None


def _check_runtime() -> list[dict]:
    out = []
    # Display / desktop control possible at all?
    if os.name == "nt":
        out.append({"group": "Runtime", "name": "Desktop control", "ok": True,
                    "detail": "Windows — supported", "why": "opening apps, typing", "fix": None})
    else:
        out.append({"group": "Runtime", "name": "Desktop control", "ok": False,
                    "detail": f"{platform.system()} — Jarvis desktop control targets Windows",
                    "why": "opening apps, typing", "fix": "Run Jarvis on the Windows machine"})
    # Disk
    try:
        import psutil
        d = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
        ok = d.free > 2e9
        out.append({"group": "Runtime", "name": "Free disk", "ok": ok,
                    "detail": f"{d.free/1e9:.1f} GB free",
                    "why": "models + screenshots + database",
                    "fix": None if ok else "Free up at least 2GB"})
        m = psutil.virtual_memory()
        ok = m.total > 7e9
        out.append({"group": "Runtime", "name": "RAM", "ok": ok,
                    "detail": f"{m.total/1e9:.0f} GB total, {m.percent}% used",
                    "why": "local models are memory-hungry",
                    "fix": None if ok else "Use smaller models (qwen2.5:1.5b)"})
    except Exception:
        pass
    # Vault key. NOTE: a broken/partial `cryptography` install can raise
    # pyo3 PanicException, which is a BaseException — so catch BaseException
    # here. A diagnostics page must never be the thing that crashes.
    try:
        from services.vault import HAS_CRYPTO
        out.append({"group": "Runtime", "name": "Credential vault", "ok": HAS_CRYPTO,
                    "detail": "encryption ready" if HAS_CRYPTO else "cryptography missing",
                    "why": "storing freelance logins safely",
                    "fix": None if HAS_CRYPTO else "pip install cryptography"})
    except BaseException as e:
        out.append({"group": "Runtime", "name": "Credential vault", "ok": False,
                    "detail": f"cryptography broken ({type(e).__name__})",
                    "why": "storing freelance logins safely",
                    "fix": "pip install --force-reinstall cryptography"})
    return out


def deep_check() -> dict:
    checks = (_check_packages() + _check_binaries()
              + _check_ollama_models() + _check_runtime())
    missing = [c for c in checks if not c["ok"]]
    blocking = [c for c in missing if c["group"] in ("Binary", "Ollama")
                or c["name"] in ("pyautogui", "mss", "psutil")]
    return {
        "ts": _now(),
        "ok": not missing,
        "summary": ("Everything Jarvis needs is installed."
                    if not missing else
                    f"{len(missing)} thing(s) missing — "
                    f"{len(blocking)} of them affect features you're using."),
        "missing_count": len(missing),
        "checks": checks,
        "fixes": [c["fix"] for c in missing if c.get("fix")],
    }


# ── Downloadable runtime report ───────────────────────────────────────────────

def _log_tail(limit_bytes: int = 120_000) -> str:
    """Tail of any jarvis log file we can find (best effort)."""
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent
    for name in ("jarvis.log", "backend.log", "logs/jarvis.log"):
        p = base / name
        if p.exists():
            try:
                data = p.read_bytes()
                return data[-limit_bytes:].decode("utf-8", errors="replace")
            except Exception:
                pass
    return "(no log file on disk — Jarvis logs to the console window by default)"


def build_report() -> str:
    """One text file with everything needed to debug this machine's run."""
    buf = io.StringIO()
    w = buf.write

    w("=" * 78 + "\nJARVIS RUNTIME REPORT\n")
    w(f"generated: {_now()}\n" + "=" * 78 + "\n\n")

    # environment
    w("## ENVIRONMENT\n")
    w(f"platform : {platform.platform()}\n")
    w(f"python   : {sys.version.split()[0]} ({sys.executable})\n")
    try:
        import psutil
        w(f"cpu      : {psutil.cpu_percent(interval=None)}%  cores={psutil.cpu_count()}\n")
        vm = psutil.virtual_memory()
        w(f"memory   : {vm.percent}% used of {vm.total/1e9:.1f} GB\n")
    except Exception:
        pass
    w("\n")

    # diagnosis
    diag = deep_check()
    w("## DIAGNOSIS\n")
    w(f"{diag['summary']}\n\n")
    group = None
    for c in diag["checks"]:
        if c["group"] != group:
            group = c["group"]
            w(f"\n-- {group} --\n")
        mark = "OK  " if c["ok"] else "MISS"
        w(f"[{mark}] {c['name']:<26} {c['detail']}\n")
        if not c["ok"] and c.get("fix"):
            w(f"        fix: {c['fix']}\n")
    w("\n")
    if diag["fixes"]:
        w("## COMMANDS TO RUN\n")
        for f in diag["fixes"]:
            w(f"  {f}\n")
        w("\n")

    # live state
    w("## LIVE STATE\n")
    try:
        from services.os_state import snapshot
        s = snapshot(timeline_limit=60)
        w(json.dumps({k: v for k, v in s.items() if k != "timeline"},
                     indent=2, default=str)[:20000] + "\n\n")
        w("## RECENT ACTIVITY\n")
        for e in s.get("timeline", []):
            w(f"  {e.get('ts','')} [{e.get('agent','')}] {e.get('msg','')}\n")
    except Exception as e:
        w(f"(state unavailable: {e})\n")
    w("\n")

    # what Jarvis has learned about THIS machine — the second-most useful
    # section when something "works on one PC but not here"
    w("## LEARNED BEHAVIOUR (observed on this machine)\n")
    try:
        from services import experience
        exp = experience.summary(12)
        o = exp.get("overall") or {}
        if o.get("samples"):
            w(f"overall: {int((o['rate'] or 0)*100)}% of the last {o['samples']} "
              f"actions succeeded")
            if o.get("top_failure"):
                w(f" — most common failure: {o['top_failure']} ({o.get('top_failure_cause','')})")
            w("\n\n")
        else:
            w("no observations recorded yet\n\n")
        if exp.get("apps"):
            w("  app                  runs  success  learned wait\n")
            for a in exp["apps"]:
                wait = f"{a['learned_wait_s']}s" if a.get("learned_wait_s") else "-"
                w(f"  {a['app'][:20]:<20} {a['runs']:>4}  {int(a['success_rate']*100):>6}%  {wait:>12}\n")
            w("\n")
        if exp.get("recent_failures"):
            w("recent failures, with cause and fix:\n")
            for f in exp["recent_failures"]:
                w(f"  [{f['kind']}] {f['app'] or '-'} / {f['action']}  ({f['at']})\n")
                w(f"      cause : {f['cause']}\n")
                w(f"      fix   : {f['remedy']}\n")
    except Exception as e:
        w(f"(experience unavailable: {e})\n")
    w("\n")

    # execution traces — the most useful part for debugging a bad command
    w("## EXECUTION TRACES (exact path each request took)\n")
    try:
        from services import trace
        for t in trace.recent(15):
            status = "OK" if t.get("ok") else ("FAIL" if t.get("ok") is False else "…")
            w(f"\n[{status}] {t['kind']}: {t['label']}  ({t.get('duration_ms','?')}ms)\n")
            for st in t.get("steps", []):
                m = "OK " if st.get("ok") else ("ERR" if st.get("ok") is False else "-  ")
                w(f"    {m} {st['component']:<32} {st.get('detail','')}  [{st.get('at_ms')}ms]\n")
            if t.get("result"):
                w(f"    -> {t['result']}\n")
    except Exception as e:
        w(f"(traces unavailable: {e})\n")
    w("\n")

    w("## LOG TAIL\n")
    w(_log_tail() + "\n")

    return buf.getvalue()
