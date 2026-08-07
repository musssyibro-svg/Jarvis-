"""
routes/system.py — System Doctor: reliability diagnostics.

The highest-leverage answer to "automation works only intermittently": tell the
user EXACTLY what capability is present, what's missing, and the one command to
fix each. Turns silent/partial failures into a checklist. Everything here is a
cheap local probe — safe to call anytime.

GET /system/doctor  -> {ok, summary, checks: [{name, ok, detail, fix}]}
"""
import os
import shutil
import sys

from fastapi import APIRouter

router = APIRouter()


def _check_python() -> dict:
    v = sys.version_info
    ok = v >= (3, 10)
    return {"name": "Python", "ok": ok,
            "detail": f"{v.major}.{v.minor}.{v.micro}",
            "fix": None if ok else "Install Python 3.11+"}


def _check_ollama() -> dict:
    try:
        import requests
        url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        r = requests.get(f"{url}/api/tags", timeout=2)
        models = [m.get("name", "") for m in r.json().get("models", [])]
        return {"name": "Ollama", "ok": True,
                "detail": f"running, {len(models)} model(s): {', '.join(models[:6]) or 'none'}",
                "fix": None if models else "Pull a chat model: ollama pull qwen2.5:0.5b"}
    except Exception:
        return {"name": "Ollama", "ok": False, "detail": "not reachable on :11434",
                "fix": "Start it: ollama serve  (install from ollama.com)"}


def _check_model(role: str, env: str, default: str, pull_hint: str) -> dict:
    want = os.getenv(env, default)
    try:
        import requests
        url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        r = requests.get(f"{url}/api/tags", timeout=2)
        models = [m.get("name", "") for m in r.json().get("models", [])]
        base = want.split(":")[0]
        ok = any(m == want or m.startswith(base) for m in models)
        return {"name": f"Model: {role}", "ok": ok,
                "detail": want if ok else f"'{want}' not installed",
                "fix": None if ok else f"ollama pull {pull_hint}"}
    except Exception:
        return {"name": f"Model: {role}", "ok": False, "detail": "Ollama down",
                "fix": f"ollama pull {pull_hint}"}


def _check_tesseract() -> dict:
    # Trap #1: pytesseract (pip) can import while the tesseract BINARY is absent.
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return {"name": "OCR (Tesseract)", "ok": False, "detail": "pytesseract package missing",
                "fix": "pip install pytesseract AND install the Tesseract binary "
                       "(https://github.com/UB-Mannheim/tesseract/wiki)"}
    binary = shutil.which("tesseract")
    if not binary and os.name == "nt":
        for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
                  os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe")):
            if os.path.exists(c):
                binary = c
                break
    if not binary:
        return {"name": "OCR (Tesseract)", "ok": False,
                "detail": "package OK but BINARY not found",
                "fix": "Install the Tesseract binary (the pip package alone is not "
                       "enough): https://github.com/UB-Mannheim/tesseract/wiki"}
    # Trap #2: binary present but language data (eng.traineddata) missing ->
    # "Could not initialize tesseract". vision_agent self-heals this on first
    # OCR use by downloading eng.traineddata; the probe reports the live state.
    try:
        from agents.vision_agent import tessdata_ready
        if not tessdata_ready():
            return {"name": "OCR (Tesseract)", "ok": False,
                    "detail": f"binary at {binary} but English language data missing",
                    "fix": "Jarvis auto-downloads eng.traineddata on first OCR use "
                           "(needs internet once). Manual: put "
                           "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata "
                           "into the 'tessdata' folder next to tesseract.exe"}
    except Exception:
        pass
    return {"name": "OCR (Tesseract)", "ok": True,
            "detail": f"binary at {binary}, languages OK", "fix": None}


def _check_screenshot() -> dict:
    have = []
    for mod in ("mss", "PIL", "pyautogui"):
        try:
            __import__(mod)
            have.append(mod)
        except ImportError:
            pass
    ok = "mss" in have or "pyautogui" in have
    return {"name": "Screenshot", "ok": ok,
            "detail": f"available: {', '.join(have) or 'none'}",
            "fix": None if ok else "pip install mss Pillow"}


def _check_desktop() -> dict:
    try:
        import pyautogui  # noqa: F401
        return {"name": "Desktop control", "ok": True, "detail": "pyautogui present", "fix": None}
    except Exception:
        return {"name": "Desktop control", "ok": False, "detail": "pyautogui missing",
                "fix": "pip install pyautogui pygetwindow"}


def _check_playwright() -> dict:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return {"name": "Browser (Playwright)", "ok": False, "detail": "package missing",
                "fix": "pip install playwright && python -m playwright install chromium"}
    # package present — is a browser actually installed?
    from pathlib import Path
    candidates = [
        Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH", "")) if os.getenv("PLAYWRIGHT_BROWSERS_PATH") else None,
        Path.home() / "AppData/Local/ms-playwright" if os.name == "nt" else None,
        Path.home() / ".cache/ms-playwright",
    ]
    found = any(p and p.exists() and any(p.glob("chromium*")) for p in candidates)
    return {"name": "Browser (Playwright)", "ok": found,
            "detail": "chromium installed" if found else "package OK but no browser binary",
            "fix": None if found else "python -m playwright install chromium"}


def _check_brain_embeddings() -> dict:
    try:
        from services.brain_service import EMBED_MODEL, embeddings_available
        ok = embeddings_available(force=True)
        return {"name": "Brain semantic search", "ok": ok,
                "detail": f"{EMBED_MODEL} ready" if ok else "keyword-only (still works)",
                "fix": None if ok else f"ollama pull {EMBED_MODEL}  (~274MB, optional)"}
    except Exception as e:
        return {"name": "Brain semantic search", "ok": False, "detail": str(e),
                "fix": "check backend logs"}


def _check_resources() -> dict:
    try:
        import psutil
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
        ram_gb = ram.available / 1e9
        disk_gb = disk.free / 1e9
        warn = []
        if ram_gb < 2:
            warn.append(f"low free RAM ({ram_gb:.1f}GB)")
        if disk_gb < 3:
            warn.append(f"low free disk ({disk_gb:.1f}GB)")
        return {"name": "Resources", "ok": not warn,
                "detail": f"{ram_gb:.1f}GB RAM free, {disk_gb:.1f}GB disk free"
                          + (f" — {'; '.join(warn)}" if warn else ""),
                "fix": None if not warn else "Close apps / free disk; keep models <=3B on 16GB"}
    except Exception as e:
        return {"name": "Resources", "ok": True, "detail": f"unavailable: {e}", "fix": None}


@router.get("/doctor")
def doctor():
    checks = [
        _check_python(),
        _check_ollama(),
        _check_model("fast/chat", "OLLAMA_FAST_MODEL", "qwen2.5:0.5b", "qwen2.5:0.5b"),
        _check_model("reasoning", "OLLAMA_REASONING_MODEL", "deepseek-r1:1.5b", "deepseek-r1:1.5b"),
        _check_brain_embeddings(),
        _check_screenshot(),
        _check_desktop(),
        _check_tesseract(),
        _check_playwright(),
        _check_resources(),
    ]
    passing = sum(1 for c in checks if c["ok"])
    return {
        "ok": passing == len(checks),
        "summary": f"{passing}/{len(checks)} checks passing",
        "checks": checks,
        "todo": [{"name": c["name"], "fix": c["fix"]} for c in checks if not c["ok"] and c["fix"]],
    }
