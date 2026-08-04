"""
RUNTIME_VALIDATION.py — run on the TARGET WINDOWS PC (not in any sandbox).

Runs the 4 required commands through the real V9 stack and captures:
  - SSE event log per command
  - before/after screenshots (saved as PNG)
  - error traces if anything fails

Usage (Windows, with backend deps installed + Ollama running):
    cd backend
    python ../RUNTIME_VALIDATION.py

Output goes to ./runtime_validation_<timestamp>/ :
    sse_log.txt, results.json, *.png screenshots

This file performs REAL actions (opens Notepad/Chrome, screenshots your screen).
It is the proof artifact your checkpoint requires — produced by YOU running it on
the real machine, because that evidence cannot be generated anywhere else.
"""
import sys
import os
import json
import traceback
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
sys.path.insert(0, os.path.dirname(__file__))

OUT = os.path.join(os.getcwd(),
                   "runtime_validation_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
os.makedirs(OUT, exist_ok=True)
sse_log = []


def _capture_sse():
    """Mirror the SSE feed into our log list."""
    import agents.orchestrator as orch
    real = orch.STATE.emit
    def tap(agent, msg, level="info"):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] [{agent}] {msg} ({level})"
        sse_log.append(line); print(line)
        return real(agent, msg, level)
    orch.STATE.emit = tap


def _shot(name):
    """Save a real screenshot via desktop_agent; returns path or error."""
    try:
        from agents import desktop_agent as da
        r = da.screenshot()
        src = r.get("path")
        if src and os.path.exists(src):
            dst = os.path.join(OUT, name + ".png")
            import shutil; shutil.copy(src, dst)
            return dst
        return f"(no screenshot path returned: {r})"
    except Exception as e:
        return f"(screenshot failed: {e})"


def run_cmd(label, message):
    print(f"\n===== {label}: '{message}' =====")
    entry = {"label": label, "command": message,
             "before_shot": _shot(f"{label}_before")}
    try:
        from adapters.commander_adapter import handle_chat
        result = handle_chat(message, "runtime_validation")
        entry["result"] = result
        entry["ok"] = bool(result.get("response"))
    except Exception:
        entry["error"] = traceback.format_exc()
        entry["ok"] = False
    import time; time.sleep(2)   # let the action settle
    entry["after_shot"] = _shot(f"{label}_after")
    return entry


def main():
    _capture_sse()
    results = []
    results.append(run_cmd("open_notepad", "open notepad"))
    results.append(run_cmd("open_chrome",  "open chrome"))
    results.append(run_cmd("screenshot",   "take a screenshot"))
    results.append(run_cmd("auto_mode",    "start autonomous mode"))

    with open(os.path.join(OUT, "sse_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sse_log))
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n===== DONE. Artifacts in: {OUT} =====")
    for r in results:
        print(f"  {r['label']}: {'OK' if r.get('ok') else 'FAILED'}")
    print("\nSend back: sse_log.txt, results.json, and the *.png files.")


if __name__ == "__main__":
    main()
