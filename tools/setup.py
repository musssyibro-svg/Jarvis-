"""
tools/setup.py - install everything Jarvis needs, then say what's left.

Driven by START.bat. Safe to run repeatedly: every step checks first and skips
what's already done, so a second run takes seconds.

Deliberately does NOT install Python, Node or Ollama. Those need a real
installer and a PATH change that only takes effect in a NEW terminal, so
pretending to handle them would produce a script that appears to succeed and
then fails confusingly. It reports them clearly with the download link instead.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
CN = os.getenv("JARVIS_CN", "1") == "1"

PIP_MIRROR = ["--index-url", "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple",
              "--trusted-host", "mirrors.tuna.tsinghua.edu.cn"] if CN else []

# Models Jarvis actually needs, smallest useful first.
WANT_MODELS = [
    ("qwen2.5:3b", "thinking, chat and proposals", True),
    ("llava:7b",   "understanding what's on screen", False),
]
# Models worth deleting to reclaim disk - with the reason.
JUNK_MODELS = {
    "qwen2.5:0.5b": "too small to follow instructions; superseded by qwen2.5:3b",
    "qwen:latest":  "older generation than qwen2.5",
    "qwen2:7b":     "4.4GB and overlapping with qwen2.5:3b",
    "deepseek-r1:latest": "7B reasoning model; heavy for 16GB alongside llava",
}

_problems, _notes = [], []


def say(msg=""):
    print(msg, flush=True)


def step(n, total, title):
    say(f"\n[{n}/{total}] {title}")


def run(cmd, timeout=900, quiet=True):
    try:
        r = subprocess.run(cmd, capture_output=quiet, text=True, timeout=timeout)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")) if quiet else ""
    except FileNotFoundError:
        return False, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


# ── prerequisites we can only report on ──────────────────────────────────────

def check_prereqs():
    ok = True
    v = sys.version_info
    if v < (3, 10):
        _problems.append(f"Python {v.major}.{v.minor} is too old - install 3.11 from python.org")
        ok = False
    else:
        say(f"      Python {v.major}.{v.minor}.{v.micro}  ok")

    if not (shutil.which("node") and (shutil.which("npm") or shutil.which("npm.cmd"))):
        _problems.append("Node.js is missing - install the LTS build from nodejs.org, "
                         "then run this again in a NEW terminal")
        ok = False
    else:
        say("      Node.js + npm  ok")

    if not shutil.which("ollama"):
        _problems.append("Ollama is missing - install from ollama.com, then run this again")
        ok = False
    else:
        say("      Ollama  ok")
    return ok


# ── python packages ──────────────────────────────────────────────────────────

def install_python_packages():
    req = BACKEND / "requirements.txt"
    if not req.is_file():
        _problems.append(f"{req} is missing - the download is incomplete")
        return
    base = [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)]
    say("      installing (first run takes a few minutes)...")
    ok, out = run(base + PIP_MIRROR)
    if not ok and PIP_MIRROR:
        say("      mirror failed, retrying against PyPI directly...")
        ok, out = run(base)
    if not ok:
        _problems.append("Python packages failed to install. Last error:\n        "
                         + (out or "")[-400:])
        return

    # pywin32 isn't in requirements (it's Windows-only) but without it Jarvis
    # can't tell an image on the clipboard from text, and will overwrite it.
    if os.name == "nt":
        try:
            import win32clipboard  # noqa: F401
        except ImportError:
            run([sys.executable, "-m", "pip", "install", "-q", "pywin32"] + PIP_MIRROR)
    say("      done")


# ── playwright browser ───────────────────────────────────────────────────────

def install_browser():
    try:
        import playwright  # noqa: F401
    except ImportError:
        _problems.append("playwright package missing - the pip step above failed")
        return
    root = Path(os.path.expandvars(
        r"%LOCALAPPDATA%\ms-playwright" if os.name == "nt" else "~/.cache/ms-playwright")).expanduser()
    if root.is_dir() and any(p.name.startswith("chromium") for p in root.iterdir()):
        say("      already installed")
        return
    env = dict(os.environ)
    if CN:
        # Mirror only works for `chromium`. `playwright install chrome` pulls
        # Google's MSI through a script that ignores this variable entirely and
        # can never succeed from mainland China.
        env["PLAYWRIGHT_DOWNLOAD_HOST"] = "https://npmmirror.com/mirrors/playwright"
    say("      downloading (~150MB, first run only)...")
    try:
        r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                           env=env, capture_output=True, text=True, timeout=1800)
        if r.returncode == 0:
            say("      done")
        else:
            _problems.append("Browser download failed. Freelance automation won't work.\n"
                             "        Retry:  python -m playwright install chromium")
    except Exception as e:
        _problems.append(f"Browser download failed: {str(e)[:120]}")


# ── frontend packages ────────────────────────────────────────────────────────

def install_frontend():
    if not (FRONTEND / "package.json").is_file():
        _problems.append("frontend/package.json missing - the download is incomplete")
        return
    if (FRONTEND / "node_modules").is_dir():
        say("      already installed")
        return
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        return
    cmd = [npm, "install", "--no-audit", "--no-fund"]
    if CN:
        cmd += ["--registry=https://registry.npmmirror.com"]
    say("      installing (first run takes a few minutes)...")
    try:
        r = subprocess.run(cmd, cwd=str(FRONTEND), capture_output=True,
                           text=True, timeout=1800)
        if r.returncode != 0 and CN:
            say("      mirror failed, retrying against the npm registry...")
            r = subprocess.run([npm, "install", "--no-audit", "--no-fund"],
                               cwd=str(FRONTEND), capture_output=True,
                               text=True, timeout=1800)
        if r.returncode == 0:
            say("      done")
        else:
            _problems.append("UI packages failed to install:\n        "
                             + (r.stderr or "")[-300:])
    except Exception as e:
        _problems.append(f"UI packages failed: {str(e)[:120]}")


# ── ollama models + disk ─────────────────────────────────────────────────────

def _installed_models():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=4) as r:
            return [m.get("name") or m.get("model")
                    for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:
        return None


def _free_gb(path):
    try:
        return shutil.disk_usage(str(path)).free / 1e9
    except Exception:
        return 999.0


def setup_models():
    models = _installed_models()
    if models is None:
        say("      starting Ollama...")
        try:
            subprocess.Popen(["ollama", "serve"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        import time
        for _ in range(10):
            time.sleep(1.5)
            models = _installed_models()
            if models is not None:
                break
    if models is None:
        _problems.append("Ollama isn't responding. Open a terminal and run:  ollama serve")
        return

    say(f"      installed: {', '.join(models) if models else '(none)'}")

    # Reclaim space BEFORE pulling, or a full disk stops the pull.
    junk = [m for m in models if m in JUNK_MODELS]
    free = _free_gb(ROOT)
    if junk and free < 12:
        say(f"      only {free:.1f}GB free - removing models that aren't earning their space:")
        for m in junk:
            # Never remove a model if it's the only one that can do a job.
            others = [x for x in models if x not in JUNK_MODELS]
            if not others and m == junk[-1]:
                break
            say(f"        {m}  ({JUNK_MODELS[m]})")
            if run(["ollama", "rm", m])[0]:
                models.remove(m)
        _notes.append("Removed redundant Ollama models to free disk space.")
    elif junk:
        _notes.append("These models can be removed to save space when you need it: "
                      + ", ".join(f"ollama rm {m}" for m in junk))

    for name, why, required in WANT_MODELS:
        if any(m == name or m.startswith(name.split(":")[0] + ":") for m in models):
            continue
        free = _free_gb(ROOT)
        if free < 6:
            _problems.append(f"Only {free:.1f}GB free - not enough room for {name} ({why}).\n"
                             f"        Free up space, then:  ollama pull {name}")
            continue
        say(f"      pulling {name} - {why} (this is a big download)")
        if not run(["ollama", "pull", name], timeout=3600, quiet=False)[0]:
            msg = f"Couldn't pull {name} ({why}). Retry manually:  ollama pull {name}"
            (_problems if required else _notes).append(msg)


def main():
    say("=" * 70)
    say("  JARVIS - SETUP")
    say(f"  {ROOT}")
    if CN:
        say("  China mirrors ON (set JARVIS_CN=0 to use upstream sources)")
    say("=" * 70)

    step(1, 5, "Checking Python, Node and Ollama")
    if not check_prereqs():
        say("\n" + "=" * 70)
        say("  MISSING PREREQUISITES - install these first:")
        for p in _problems:
            say(f"    - {p}")
        say("=" * 70)
        return 1

    step(2, 5, "Python packages")
    install_python_packages()

    step(3, 5, "Automation browser (Playwright chromium)")
    install_browser()

    step(4, 5, "UI packages")
    install_frontend()

    step(5, 5, "AI models")
    setup_models()

    say("\n" + "=" * 70)
    if _problems:
        say(f"  SETUP FINISHED WITH {len(_problems)} PROBLEM(S)")
        for p in _problems:
            say(f"    - {p}")
        say("\n  Jarvis may still start, but the features above won't work.")
    else:
        say("  SETUP COMPLETE - everything Jarvis needs is installed.")
    for n in _notes:
        say(f"\n  Note: {n}")
    free = _free_gb(ROOT)
    if free < 5:
        say(f"\n  WARNING: only {free:.1f}GB free on this drive. Jarvis writes "
            f"screenshots\n  and a database as it runs, and models need room to load.")
    say("=" * 70)
    return 1 if _problems else 0


if __name__ == "__main__":
    sys.exit(main())
