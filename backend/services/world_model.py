"""
services/world_model.py — Jarvis's live picture of reality.

GPT's note was right: the World Model shouldn't be a service everyone RPCs into,
it's the Brain's internal understanding of what's true right now. So this module
is deliberately thin data + a change detector, and brain_core exposes it.

It answers: what apps/windows are open, which freelance platforms are logged in,
what's the system load, is the income engine running, which plans are active,
which model is live. A background poller diffs successive snapshots and PUBLISHES
change events ("app.opened", "app.closed", "login.changed", "system.ram_high")
so the rest of Jarvis can react proactively instead of waiting to be asked.
"""
import threading
import time
from datetime import datetime, timezone

from services import event_bus

_last: dict = {}
_lock = threading.Lock()
_started = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_windows() -> list[str]:
    try:
        from agents.desktop_agent import list_windows
        r = list_windows()
        return r.get("windows", []) if r.get("success") else []
    except Exception:
        return []


def _running_apps() -> list[str]:
    """A small set of 'interesting' foreground apps, not the whole process table."""
    interesting = {"chrome", "msedge", "firefox", "notepad", "code", "qq", "wechat",
                   "telegram", "discord", "spotify", "word", "excel", "powerpnt",
                   "outlook", "steam", "explorer"}
    found = set()
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower().replace(".exe", "")
            if n in interesting:
                found.add(n)
    except Exception:
        pass
    return sorted(found)


def _system() -> dict:
    try:
        import psutil, os
        disk = "C:\\" if os.name == "nt" else "/"
        return {"cpu": round(psutil.cpu_percent(interval=0.1)),
                "ram": round(psutil.virtual_memory().percent),
                "disk": round(psutil.disk_usage(disk).percent)}
    except Exception:
        return {"cpu": 0, "ram": 0, "disk": 0}


def _logins() -> list[str]:
    try:
        from services import session_manager
        return session_manager.logged_in_platforms()
    except Exception:
        return []


def _income() -> dict:
    try:
        from services import income_engine
        s = income_engine.status()
        return {"enabled": s.get("enabled"), "cycles": s.get("cycles"),
                "interval_min": s.get("interval_min")}
    except Exception:
        return {}


def _active_plans() -> list[str]:
    try:
        from services import planner_service
        return [p["title"] for p in planner_service.list_projects()
                if p.get("status") == "active"][:8]
    except Exception:
        return []


def _model() -> str:
    try:
        from services.deepseek_service import OLLAMA_FAST_MODEL
        return OLLAMA_FAST_MODEL
    except Exception:
        return ""


def snapshot(fast: bool = True) -> dict:
    """Current world state. fast=True skips the ~0.1s CPU sample for hot paths."""
    return {
        "ts":         _now(),
        "windows":    _open_windows(),
        "apps":       _running_apps(),
        "logins":     _logins(),
        "system":     ({} if fast else _system()),
        "income":     _income(),
        "plans":      _active_plans(),
        "model":      _model(),
    }


def summary() -> str:
    """One-paragraph natural-language state, for injecting into the Brain/LLM."""
    s = snapshot(fast=False)
    parts = []
    if s["apps"]:
        parts.append("open apps: " + ", ".join(s["apps"]))
    if s["logins"]:
        parts.append("logged in to: " + ", ".join(s["logins"]))
    if s["income"].get("enabled"):
        parts.append(f"income engine running ({s['income'].get('cycles',0)} cycles)")
    if s["plans"]:
        parts.append("active plans: " + ", ".join(s["plans"]))
    sysd = s["system"]
    if sysd:
        parts.append(f"CPU {sysd['cpu']}% / RAM {sysd['ram']}%")
    return "; ".join(parts) if parts else "idle, nothing notable open"


# ── Change detection -> proactive events ──────────────────────────────────────

def _diff_and_publish(prev: dict, cur: dict) -> None:
    prev_apps, cur_apps = set(prev.get("apps", [])), set(cur.get("apps", []))
    for opened in cur_apps - prev_apps:
        event_bus.publish("app.opened", {"app": opened})
    for closed in prev_apps - cur_apps:
        event_bus.publish("app.closed", {"app": closed})

    prev_log, cur_log = set(prev.get("logins", [])), set(cur.get("logins", []))
    for p in cur_log - prev_log:
        event_bus.publish("login.changed", {"platform": p, "state": "logged_in"})
    for p in prev_log - cur_log:
        event_bus.publish("login.changed", {"platform": p, "state": "logged_out"})

    ram = cur.get("system", {}).get("ram", 0)
    if ram >= 90 and prev.get("system", {}).get("ram", 0) < 90:
        event_bus.publish("system.ram_high", {"ram": ram}, emit_feed=True, level="warning")


def _poll_loop():
    global _last
    time.sleep(20)
    while True:
        try:
            cur = snapshot(fast=False)
            with _lock:
                prev = dict(_last)
                _last = cur
            if prev:
                _diff_and_publish(prev, cur)
        except Exception:
            pass
        time.sleep(15)


def get_cached() -> dict:
    with _lock:
        return dict(_last) if _last else snapshot()


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_poll_loop, daemon=True, name="jarvis-world-model").start()
