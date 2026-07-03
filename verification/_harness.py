"""
verification/_harness.py  —  Jarvis V8 Verification Harness (Final)

Key design rules:
- Boolean-only evidence is rejected; passing check needs substantive data
- SKIP is distinct from FAIL — used when a dependency is simply not installed
- RAM snapshots captured at each call via psutil (always available in requirements)
- Screenshot capture helper (mss/pyautogui, degrades gracefully)
- Artifact collectors: process dumps, Ollama status dumps
- Temp DB cleanup registered automatically
- Old artifact cleanup (files > N days) available on request
"""
import os
import sys
import json
import time
import atexit
import shutil
import traceback
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
BACKEND     = ROOT / "backend"
RESULTS     = Path(__file__).resolve().parent / "results"
SCREENSHOTS = RESULTS / "screenshots"
ARTIFACTS   = RESULTS / "artifacts"

for _d in (RESULTS, SCREENSHOTS, ARTIFACTS):
    _d.mkdir(parents=True, exist_ok=True)

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# ── Temp-file registry (auto-cleaned at exit) ─────────────────────────────────
_TEMP_FILES = []

def register_temp(path: str):
    """Register a path for automatic deletion when the test process exits."""
    _TEMP_FILES.append(str(path))

def _cleanup_temps():
    for p in _TEMP_FILES:
        try:
            if Path(p).is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif Path(p).exists():
                Path(p).unlink(missing_ok=True)
        except Exception:
            pass

atexit.register(_cleanup_temps)


def cleanup_old_artifacts(days: int = 7):
    """
    Remove artifact files older than `days` days.
    Call explicitly from run_all_tests.py if desired.
    """
    cutoff = time.time() - days * 86_400
    removed = 0
    for folder in (SCREENSHOTS, ARTIFACTS):
        for f in folder.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                removed += 1
    return removed


# ── Time helpers ──────────────────────────────────────────────────────────────
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def ts():
    return datetime.now().strftime("%H%M%S")


# ── RAM monitoring ────────────────────────────────────────────────────────────
def ram_snapshot(label: str = "") -> dict:
    """
    Capture current RAM usage via psutil.
    Returns a dict with used_mb, available_mb, percent, process_rss_mb.
    Always works — psutil is in requirements.txt.
    """
    try:
        import psutil
        vm  = psutil.virtual_memory()
        rss = psutil.Process().memory_info().rss // 1024 ** 2
        snap = {
            "label":           label,
            "timestamp":       now_iso(),
            "total_mb":        vm.total      // 1024 ** 2,
            "used_mb":         vm.used       // 1024 ** 2,
            "available_mb":    vm.available  // 1024 ** 2,
            "percent":         vm.percent,
            "process_rss_mb":  rss,
        }
    except Exception as e:
        snap = {"label": label, "timestamp": now_iso(), "error": str(e)}
    return snap


def save_ram_artifact(snapshots: list, label: str) -> str:
    """Save a list of RAM snapshots to an artifact file. Returns path."""
    path = str(ARTIFACTS / f"ram_{label}_{ts()}.json")
    Path(path).write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    return path


# ── Evidence validation ────────────────────────────────────────────────────────
def _is_substantive(evidence) -> bool:
    """
    Reject boolean-only or empty evidence.
    A plain True/False/None/empty-dict/empty-list does NOT count.
    """
    if evidence is None or isinstance(evidence, bool):
        return False
    if isinstance(evidence, dict):
        return any(
            v is not None and not isinstance(v, bool)
            for v in evidence.values()
        )
    if isinstance(evidence, list):
        return len(evidence) > 0
    if isinstance(evidence, str):
        return len(evidence.strip()) > 5
    if isinstance(evidence, (int, float)):
        return True
    return False


# ── Screenshot helper ──────────────────────────────────────────────────────────
def capture_screenshot(name: str) -> str | None:
    """Take a screenshot using mss or pyautogui. Returns saved path or None."""
    path = str(SCREENSHOTS / f"{name}_{ts()}.png")
    try:
        import mss, io
        from PIL import Image
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            img.save(path)
        return path
    except Exception:
        pass
    try:
        import pyautogui
        pyautogui.screenshot().save(path)
        return path
    except Exception:
        return None


# ── Process helpers ────────────────────────────────────────────────────────────
def process_running(name: str) -> bool:
    """Check if a process is running by name (psutil or tasklist)."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if name.lower() in (p.info["name"] or "").lower():
                return True
        return False
    except ImportError:
        pass
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode(errors="ignore")
        return name.lower() in out.lower()
    except Exception:
        return False


def dump_process_list(label: str) -> str:
    """Dump running processes to an artifact file. Returns path."""
    path = str(ARTIFACTS / f"processes_{label}_{ts()}.txt")
    try:
        import psutil
        lines = [f"{p.pid:6}  {p.info['name']}"
                 for p in psutil.process_iter(["name"])]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
    except ImportError:
        try:
            out = subprocess.check_output(
                ["tasklist"], stderr=subprocess.DEVNULL, timeout=10
            ).decode(errors="ignore")
            Path(path).write_text(out, encoding="utf-8")
        except Exception:
            Path(path).write_text("process list unavailable", encoding="utf-8")
    return path


def dump_ollama_status() -> str:
    """Dump Ollama model list + RAM snapshot to an artifact file."""
    path = str(ARTIFACTS / f"ollama_status_{ts()}.json")
    data: dict = {"ram": ram_snapshot("ollama_dump")}
    try:
        from services.ollama_manager import health
        data["ollama"] = health()
    except Exception as e:
        data["ollama"] = {"error": str(e)}
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ── TestRun ────────────────────────────────────────────────────────────────────
class TestRun:
    """
    Collects checks + evidence + artifacts for one test file.

    PASS  — every check ok AND at least one has substantive evidence
    FAIL  — one or more checks failed
    SKIP  — test called t.skip("reason") before completing
    """

    def __init__(self, name: str):
        self.name         = name
        self.started      = now_iso()
        self.checks       = []
        self.logs         = []
        self.artifacts    = []
        self._skipped     = False
        self._skip_reason = ""

    # ── Logging ──────────────────────────────────────────────────────────────
    def log(self, msg: str):
        line = f"[{now_iso()}] {msg}"
        print("   " + line)
        self.logs.append(line)

    # ── Skip ─────────────────────────────────────────────────────────────────
    def skip(self, reason: str):
        """
        Mark this entire test as SKIP (missing dependency, not a code failure).
        The test stops here; result = SKIP in the report.
        """
        self._skipped     = True
        self._skip_reason = reason
        self.log(f"SKIP: {reason}")

    # ── Checks ────────────────────────────────────────────────────────────────
    def check(self, label: str, ok: bool, evidence=None, error: str = None):
        substantive = _is_substantive(evidence)
        if ok and not substantive:
            self.log(f"WARN: '{label}' passed but evidence is boolean/empty → FAIL")
            ok    = False
            error = (error or "") + " | evidence rejected (boolean/empty)"

        self.checks.append({
            "label":                label,
            "ok":                   bool(ok),
            "evidence":             evidence,
            "substantive_evidence": substantive,
            "error":                error,
        })
        mark = "PASS" if ok else "FAIL"
        suffix = f"  ← {error}" if (not ok and error) else ""
        print(f"   [{mark}] {label}{suffix}")
        return ok

    # ── Artifacts ─────────────────────────────────────────────────────────────
    def add_artifact(self, path: str):
        if path and Path(path).exists():
            self.artifacts.append(str(path))
            self.log(f"Artifact saved: {Path(path).name}")
        else:
            self.log(f"Artifact missing (not saved): {path}")

    def screenshot(self, name: str) -> str | None:
        p = capture_screenshot(f"{self.name}_{name}")
        if p:
            self.add_artifact(p)
        return p

    def ram(self, label: str) -> dict:
        """Capture a RAM snapshot, log it, and return it for embedding in evidence."""
        snap = ram_snapshot(label)
        self.log(f"RAM [{label}]: used={snap.get('used_mb')}MB "
                 f"avail={snap.get('available_mb')}MB "
                 f"pct={snap.get('percent')}%")
        return snap

    # ── Finish ────────────────────────────────────────────────────────────────
    @property
    def passed(self) -> bool:
        if not self.checks or self._skipped:
            return False
        return all(c["ok"] for c in self.checks)

    def finish(self) -> dict:
        if self._skipped:
            result = "SKIP"
        elif self.passed:
            result = "PASS"
        else:
            result = "FAIL"

        report = {
            "test":        self.name,
            "result":      result,
            "skip_reason": self._skip_reason,
            "started":     self.started,
            "finished":    now_iso(),
            "checks":      self.checks,
            "artifacts":   self.artifacts,
            "logs":        self.logs,
        }
        out = RESULTS / f"{self.name}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n   → {self.name}: {result}  (report: {out.name})")
        return report


# ── Guard ─────────────────────────────────────────────────────────────────────
def guard(run: TestRun, label: str, fn):
    """Run fn(), recording any exception as a FAIL with traceback evidence."""
    try:
        return fn()
    except Exception as e:
        tb = traceback.format_exc()
        run.check(label, False,
                  evidence={"exception": f"{type(e).__name__}: {e}",
                            "traceback": tb[:1000]},
                  error=f"{type(e).__name__}: {e}")
        return None
