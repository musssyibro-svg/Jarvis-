"""
services/environment.py — what machine am I actually running on?

Jarvis kept failing in ways that were really the same failure wearing different
clothes: it assumed Chrome, it assumed Google, it assumed English window titles,
it assumed a GPU. Every one of those is the code expecting the computer to match
it, rather than the other way round.

So before doing anything, look. This module scans the machine once at startup
(and on demand) and records what is genuinely there: which browsers exist, which
messaging apps, how much RAM is free, whether there's a usable GPU, what the
system language is, whether a proxy is configured, which Ollama models are
pulled, how much disk is left.

Everything downstream reads FACTS from here instead of guessing:
  * providers.py resolves capabilities against what's installed
  * persona.py seeds "you're in China, you use Edge, you have no Chrome"
  * ollama_manager picks model sizes against real free RAM
  * diagnostics reports what's missing with the specific fix

The scan is deliberately cheap and never raises. A probe that fails records
"unknown" rather than taking the whole scan down with it — a half-known machine
is still far better than an assumed one.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()
_snapshot: dict = {}
_scanned_at: float = 0.0
_TTL = 900.0          # 15 min; a machine's shape doesn't change minute to minute


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _quiet(fn, default=None):
    """Run a probe; a failure is 'unknown', never an exception out of scan()."""
    try:
        return fn()
    except Exception:
        return default


# ── individual probes ────────────────────────────────────────────────────────

_BROWSERS = {
    "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "firefox": [r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"],
    "brave": [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "opera": [r"C:\Program Files\Opera\opera.exe"],
    "360se": [r"C:\Program Files (x86)\360\360se6\Application\360se.exe"],
    "qqbrowser": [r"C:\Program Files (x86)\Tencent\QQBrowser\QQBrowser.exe"],
}

# Apps worth knowing about by name. Resolved through app_resolver (Start Menu +
# registry), so anything installed normally is found without a hardcoded path.
_APPS_OF_INTEREST = [
    "qq", "wechat", "tim", "dingtalk", "feishu", "doubao", "telegram",
    "whatsapp", "discord", "slack", "line", "skype", "zoom",
    "notepad", "notepad++", "vscode", "word", "excel", "powerpoint", "outlook",
    "explorer", "cmd", "powershell", "calculator", "paint", "obs", "steam",
]


def _browsers() -> dict:
    found = {}
    for name, paths in _BROWSERS.items():
        hit = next((p for p in paths if os.path.exists(p)), None)
        if not hit and shutil.which(name):
            hit = shutil.which(name)
        if hit:
            found[name] = hit
    return found


def _apps() -> dict:
    """Installed apps, via the resolver that already handles Start Menu shortcuts."""
    found = {}
    try:
        from services.app_resolver import resolve as _resolve
    except Exception:
        return found
    for name in _APPS_OF_INTEREST:
        try:
            p = _resolve(name)
        except Exception:
            p = None
        if p:
            found[name] = p
    return found


def _memory() -> dict:
    import psutil
    vm = psutil.virtual_memory()
    return {"total_gb": round(vm.total / 1e9, 1),
            "free_gb": round(vm.available / 1e9, 1),
            "used_percent": vm.percent}


def _disks() -> list[dict]:
    import psutil
    out = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
        except Exception:
            continue      # empty card readers / unmounted CD drives raise here
        out.append({"drive": part.mountpoint,
                    "total_gb": round(u.total / 1e9, 1),
                    "free_gb": round(u.free / 1e9, 1),
                    "used_percent": u.percent})
    return out


def _gpu() -> dict:
    """
    Is there a GPU worth putting a model on?

    This decides whether local vision is viable at a useful speed. Getting it
    wrong in the optimistic direction is what produced a 288-second screenshot
    analysis, so an unknown GPU is treated as no GPU.
    """
    # nvidia-smi is the only reliable, dependency-free source for VRAM.
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = subprocess.run(
                [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=8)
            line = (out.stdout or "").strip().splitlines()
            if line:
                name, mem = (line[0].split(",") + ["0"])[:2]
                vram = int(float(mem.strip() or 0))
                return {"present": True, "name": name.strip(), "vram_mb": vram,
                        "usable_for_llm": vram >= 6000}
        except Exception:
            pass
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=8)
            names = [l.strip() for l in (out.stdout or "").splitlines()[1:] if l.strip()]
            if names:
                integrated = all(
                    any(k in n.lower() for k in ("intel", "uhd", "iris", "vega", "radeon graphics"))
                    for n in names)
                return {"present": True, "name": names[0], "vram_mb": None,
                        "usable_for_llm": not integrated}
        except Exception:
            pass
    return {"present": False, "name": None, "vram_mb": None, "usable_for_llm": False}


def _locale() -> dict:
    """
    System language — the reason focus-by-window-title broke.

    On a Chinese Windows install the Notepad window is 无标题 - 记事本, so
    matching the title against "Notepad" never hits. Knowing the UI language up
    front means we can stop relying on titles at all (desktop_agent matches by
    process name instead) and can tell the user why.
    """
    info = {"language": None, "encoding": None, "ui_is_english": True,
            "timezone": _quiet(lambda: time.tzname[0])}
    try:
        import locale as _loc
        lang, enc = _loc.getdefaultlocale()
        info["language"], info["encoding"] = lang, enc
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            info["ui_language_id"] = lang_id
            # 0x0804 zh-CN, 0x0404 zh-TW, 0x0411 ja, 0x0412 ko
            info["ui_is_english"] = (lang_id & 0x3FF) == 0x09
            info["ui_is_cjk"] = (lang_id & 0x3FF) in (0x04, 0x11, 0x12)
        except Exception:
            pass
    if info.get("language") and not info["language"].lower().startswith("en"):
        info["ui_is_english"] = False
    return info


def _network() -> dict:
    """
    Proxy configuration and whether we look like we're behind the GFW.

    Not a value judgement — it decides which search engine and which package
    mirrors are worth trying first, and it explains a class of "Jarvis is
    broken" reports that are really "the network refused".
    """
    proxy = {k: os.environ.get(k) for k in
             ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
             if os.environ.get(k)}
    no_proxy = os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")
    loopback_bypassed = all(h in no_proxy for h in ("127.0.0.1", "localhost"))
    china = os.getenv("JARVIS_CN", "1") == "1"
    tz = _quiet(lambda: time.tzname[0], "") or ""
    if "China" in tz or "CST" in tz:
        china = True
    return {"proxy": proxy, "proxy_set": bool(proxy),
            "loopback_bypassed": loopback_bypassed,
            "likely_china": china,
            "note": ("Loopback is NOT excluded from the proxy — Ollama calls will "
                     "be sent to the proxy and appear offline."
                     if proxy and not loopback_bypassed else "")}


def _ollama() -> dict:
    try:
        import ollama
        data = ollama.list()
        models = []
        for m in (data.get("models") or []):
            name = m.get("model") or m.get("name") or ""
            size = m.get("size") or 0
            models.append({"name": name, "size_gb": round(size / 1e9, 2)})
        return {"running": True, "models": models,
                "total_gb": round(sum(m["size_gb"] for m in models), 1)}
    except Exception as e:
        return {"running": False, "models": [], "total_gb": 0, "error": str(e)[:200]}


def _displays() -> dict:
    if os.name != "nt":
        return {"count": None, "primary": None}
    try:
        import ctypes
        u = ctypes.windll.user32
        u.SetProcessDPIAware()
        return {"count": u.GetSystemMetrics(80) or 1,   # SM_CMONITORS
                "primary": [u.GetSystemMetrics(0), u.GetSystemMetrics(1)]}
    except Exception:
        return {"count": None, "primary": None}


def _audio() -> dict:
    """Is there a microphone? Decides whether offering voice input is honest."""
    try:
        import sounddevice as sd
        ins = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        return {"microphone": bool(ins),
                "input_devices": [d["name"] for d in ins[:4]]}
    except Exception:
        return {"microphone": None, "input_devices": []}


def _runtimes() -> dict:
    out = {"python": platform.python_version()}
    for name, args in (("node", ["--version"]), ("npm", ["--version"]),
                       ("git", ["--version"])):
        exe = shutil.which(name)
        if not exe:
            out[name] = None
            continue
        try:
            r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=10)
            out[name] = (r.stdout or r.stderr or "").strip().split()[-1]
        except Exception:
            out[name] = "installed"
    try:
        import playwright  # noqa: F401
        out["playwright"] = True
    except Exception:
        out["playwright"] = False
    return out


# ── the scan ─────────────────────────────────────────────────────────────────

def scan(force: bool = False) -> dict:
    """
    Look at the machine. Cached for 15 minutes; `force=True` re-reads.

    Never raises — a probe that fails contributes "unknown" and the rest of the
    scan continues. Half a picture beats an assumption.
    """
    global _snapshot, _scanned_at
    with _lock:
        if _snapshot and not force and (time.time() - _scanned_at) < _TTL:
            return _snapshot

    env = {
        "scanned_at": _now(),
        "os": {"system": platform.system(), "release": platform.release(),
               "version": platform.version(), "machine": platform.machine(),
               "hostname": _quiet(platform.node, "")},
        "locale":   _quiet(_locale, {}),
        "memory":   _quiet(_memory, {}),
        "disks":    _quiet(_disks, []),
        "gpu":      _quiet(_gpu, {"present": False, "usable_for_llm": False}),
        "displays": _quiet(_displays, {}),
        "audio":    _quiet(_audio, {}),
        "browsers": _quiet(_browsers, {}),
        "apps":     _quiet(_apps, {}),
        "network":  _quiet(_network, {}),
        "ollama":   _quiet(_ollama, {"running": False, "models": []}),
        "runtimes": _quiet(_runtimes, {}),
    }
    env["constraints"] = _constraints(env)

    with _lock:
        _snapshot, _scanned_at = env, time.time()

    try:
        from services import event_bus
        event_bus.publish("environment.scanned",
                          {"browsers": list(env["browsers"]),
                           "gpu": env["gpu"].get("usable_for_llm"),
                           "free_ram_gb": env["memory"].get("free_gb")})
    except Exception:
        pass
    return env


def _constraints(env: dict) -> list[dict]:
    """
    The scan turned into decisions. This is the part the rest of Jarvis acts on:
    plain statements of what this machine can and cannot do, each with the
    consequence spelled out, so behaviour is explainable rather than mysterious.
    """
    out = []
    mem = env.get("memory", {})
    gpu = env.get("gpu", {})
    net = env.get("network", {})
    loc = env.get("locale", {})
    browsers = env.get("browsers", {})
    apps = env.get("apps", {})

    if not gpu.get("usable_for_llm"):
        out.append({"key": "no_gpu", "level": "info",
                    "fact": "No GPU usable for local models.",
                    "effect": "Vision runs on CPU — keep screenshot analysis to "
                              "small models and short outputs, and expect seconds "
                              "not milliseconds."})
    total = mem.get("total_gb") or 0
    if total and total <= 20:
        out.append({"key": "limited_ram", "level": "info",
                    "fact": f"{total} GB RAM total, {mem.get('free_gb')} GB free.",
                    "effect": "Models above ~7B will swap. Router caps model size "
                              "against free RAM at request time."})
    if "chrome" not in browsers:
        have = ", ".join(browsers) or "none detected"
        out.append({"key": "no_chrome", "level": "info",
                    "fact": f"Chrome is not installed (found: {have}).",
                    "effect": "Anything asking for 'the browser' uses "
                              f"{next(iter(browsers), 'edge')} instead."})
    if net.get("likely_china"):
        out.append({"key": "china_network", "level": "info",
                    "fact": "Network looks like mainland China.",
                    "effect": "Google, Docker Hub and huggingface are unreachable "
                              "without a VPN — searches go to Bing China, packages "
                              "to Tsinghua/Taobao mirrors."})
    if net.get("proxy_set") and not net.get("loopback_bypassed"):
        out.append({"key": "proxy_eats_loopback", "level": "error",
                    "fact": "A proxy is set and localhost is not excluded.",
                    "effect": "Calls to Ollama on 127.0.0.1 get sent to the proxy "
                              "and fail. Jarvis will report the model offline while "
                              "it is running.",
                    "fix": "set NO_PROXY=127.0.0.1,localhost"})
    if loc.get("ui_is_cjk") or not loc.get("ui_is_english", True):
        out.append({"key": "non_english_ui", "level": "info",
                    "fact": f"Windows UI language is {loc.get('language') or 'not English'}.",
                    "effect": "Window titles are localised, so windows are matched "
                              "by process name instead of title."})
    msg_apps = [a for a in ("qq", "wechat", "telegram", "dingtalk", "discord", "slack")
                if a in apps]
    if msg_apps:
        out.append({"key": "messaging", "level": "info",
                    "fact": f"Messaging apps installed: {', '.join(msg_apps)}.",
                    "effect": f"'send someone a message' uses {msg_apps[0]} by default."})
    smallest_disk = min((d.get("free_gb", 999) for d in env.get("disks", [])),
                        default=999)
    if smallest_disk < 5:
        out.append({"key": "low_disk", "level": "warning",
                    "fact": f"Only {smallest_disk} GB free on the tightest drive.",
                    "effect": "Model pulls and Playwright installs will fail.",
                    "fix": "ollama rm the models you don't use"})
    if not env.get("ollama", {}).get("running"):
        out.append({"key": "ollama_down", "level": "error",
                    "fact": "Ollama is not responding.",
                    "effect": "No local model — composition, vision and planning "
                              "all fall back to literal behaviour.",
                    "fix": "start Ollama, then reload"})
    return out


def summary() -> str:
    """One paragraph a human can read. Used in reports and the 'why' narrative."""
    e = scan()
    mem, gpu = e.get("memory", {}), e.get("gpu", {})
    bits = [f"{e['os'].get('system')} {e['os'].get('release')}",
            f"{mem.get('total_gb')}GB RAM ({mem.get('free_gb')}GB free)",
            (gpu.get("name") or "no usable GPU")]
    if e.get("browsers"):
        bits.append("browsers: " + ", ".join(e["browsers"]))
    msg = [a for a in ("qq", "wechat", "telegram") if a in e.get("apps", {})]
    if msg:
        bits.append("messaging: " + ", ".join(msg))
    models = e.get("ollama", {}).get("models") or []
    if models:
        bits.append(f"{len(models)} Ollama models ({e['ollama']['total_gb']}GB)")
    return "; ".join(str(b) for b in bits) + "."


def get(path: str, default=None):
    """Dotted lookup into the last scan: get('gpu.usable_for_llm')."""
    cur = scan()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def start() -> None:
    """Scan in the background at startup so nothing blocks on it."""
    threading.Thread(target=lambda: _quiet(scan), daemon=True).start()
