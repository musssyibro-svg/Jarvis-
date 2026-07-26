"""
services/model_router.py — pick the best model that's actually installed AND fits in RAM.

Replaces the old task→role lookup (which blindly trusted whatever name was in
.env — the reason a 0.5B model was silently doing everything, and Jarvis felt
dumb no matter how good the prompts were).

Now it:
  * knows the rough quality/size of common local models,
  * looks at what's REALLY installed and how much RAM is free,
  * picks the strongest model that fits for the task at hand,
  * keeps a fallback chain so a missing model degrades instead of erroring,
  * can unload a heavy model after a one-off use (16GB machines),
  * tells you plainly when everything installed is too small to be good.

This is infrastructure, deliberately: it chooses HOW to think, never WHAT to do.
That decision belongs to the brain (services/brain_decision.py).
"""
import re
import threading

# model family -> (approx GB resident, quality score 0-10)
# Quality is for ranking only; anything under ~1B genuinely can't follow
# multi-constraint instructions, which is why it scores so low.
KNOWN = {
    "qwen2.5:0.5b":     (0.6, 2.0),
    "qwen2:0.5b":       (0.6, 2.0),
    "qwen2.5:1.5b":     (1.4, 5.0),
    "qwen2:1.5b":       (1.4, 4.8),
    "qwen2.5:3b":       (2.4, 6.8),
    "qwen2.5:7b":       (5.0, 8.2),
    "llama3.2:1b":      (1.0, 4.0),
    "llama3.2:3b":      (2.4, 6.5),
    "llama3.1:8b":      (5.5, 8.4),
    "mistral:7b":       (4.7, 7.9),
    "deepseek-r1:1.5b": (1.4, 5.5),
    "deepseek-r1:7b":   (5.0, 8.5),
    "deepseek-r1:8b":   (5.5, 8.6),
    "phi3:mini":        (2.4, 6.2),
    "gemma2:2b":        (1.8, 5.6),
    "llava:7b":         (5.0, 7.5),
    "llava:13b":        (8.5, 8.3),
    "bakllava":         (5.0, 7.2),
}

# Task classes and what they need.
#   min_quality : below this the output is not worth trusting
#   vision      : needs a multimodal model
#   heavy       : worth spending RAM/time on
TASKS = {
    "chat":       {"min_quality": 4.0, "vision": False, "heavy": False},
    "proposal":   {"min_quality": 5.0, "vision": False, "heavy": False},
    "routing":    {"min_quality": 2.0, "vision": False, "heavy": False},
    "reflection": {"min_quality": 4.5, "vision": False, "heavy": False},
    "summary":    {"min_quality": 4.0, "vision": False, "heavy": False},
    "planning":   {"min_quality": 5.5, "vision": False, "heavy": True},
    "reasoning":  {"min_quality": 6.0, "vision": False, "heavy": True},
    "vision":     {"min_quality": 0.0, "vision": True,  "heavy": True},
}

_lock = threading.Lock()
_cache = {"installed": None, "at": 0.0}
_CACHE_TTL = 60.0


def _param_size(tag: str) -> float | None:
    m = re.search(r"[:\-](\d+(?:\.\d+)?)\s*b\b", (tag or "").lower())
    return float(m.group(1)) if m else None


def _profile(tag: str) -> tuple[float, float]:
    """(GB, quality) for a model tag — known table first, else estimate by size."""
    t = (tag or "").lower()
    if t in KNOWN:
        return KNOWN[t]
    for name, prof in KNOWN.items():           # match family prefix
        if t.split(":")[0] == name.split(":")[0] and _param_size(t) == _param_size(name):
            return prof
    b = _param_size(t)
    if b is None:
        return (3.0, 5.0)                      # unknown: assume mid
    gb = max(0.5, b * 0.75)                    # ~0.75GB per B at q4
    quality = 2.0 if b < 1 else min(9.0, 3.0 + b * 0.75)
    return (gb, quality)


def _is_vision(tag: str) -> bool:
    t = (tag or "").lower()
    return any(k in t for k in ("llava", "bakllava", "vision", "moondream", "minicpm-v"))


def installed_models(force: bool = False) -> list[str]:
    import time
    with _lock:
        fresh = _cache["installed"] is not None and time.time() - _cache["at"] < _CACHE_TTL
        if fresh and not force:
            return list(_cache["installed"])
    models = []
    try:
        from services.ollama_manager import _list_installed
        models = list(_list_installed() or [])
    except Exception:
        try:
            import ollama
            models = [m.get("name", "") for m in (ollama.list().get("models") or [])]
        except Exception:
            models = []
    with _lock:
        _cache["installed"] = models
        _cache["at"] = time.time()
    return list(models)


def free_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().available / 1e9
    except Exception:
        return 8.0          # assume something reasonable rather than blocking


def pick(task: str = "chat") -> dict:
    """
    Choose the best installed model for this task that fits in free RAM.
    Always returns a usable answer; `warning` explains any compromise.
    """
    spec = TASKS.get(task, TASKS["chat"])
    models = installed_models()
    if not models:
        return {"task": task, "model": None, "quality": 0, "reason": "no models installed",
                "warning": "Ollama has no models. Run: ollama pull qwen2.5:3b",
                "fallbacks": []}

    ram = free_ram_gb()
    # Keep a little headroom so we don't push the machine into swapping.
    budget = max(1.0, ram - 1.0)

    scored = []
    for m in models:
        gb, quality = _profile(m)
        if spec["vision"] != _is_vision(m):
            continue                       # vision tasks need vision models, and vice versa
        fits = gb <= budget
        # Prefer quality, but never pick something that won't fit.
        scored.append({"model": m, "gb": gb, "quality": quality, "fits": fits})

    if not scored:
        # e.g. vision requested but no multimodal model installed
        return {"task": task, "model": None, "quality": 0,
                "reason": "no suitable model",
                "warning": ("No vision model installed. Run: ollama pull llava:7b"
                            if spec["vision"] else "No suitable model installed."),
                "fallbacks": []}

    scored.sort(key=lambda x: (x["fits"], x["quality"]), reverse=True)
    best = scored[0]
    warning = None
    if not best["fits"]:
        warning = (f"{best['model']} needs ~{best['gb']:.1f}GB but only "
                   f"{ram:.1f}GB is free — it will be slow. Close some apps.")
    elif best["quality"] < spec["min_quality"]:
        warning = (f"{best['model']} is below the quality this task wants "
                   f"({best['quality']:.1f} < {spec['min_quality']:.1f}). "
                   f"Run: ollama pull qwen2.5:3b for noticeably better results.")

    return {"task": task, "model": best["model"], "quality": best["quality"],
            "gb": best["gb"], "free_ram_gb": round(ram, 1),
            "reason": f"best installed model that fits {budget:.1f}GB",
            "warning": warning,
            "fallbacks": [s["model"] for s in scored[1:4]]}


def pick_model(task: str = "chat") -> str | None:
    """Convenience: just the model name."""
    return pick(task).get("model")


def unload(model: str) -> dict:
    """Free a model from Ollama's RAM (keep_alive=0). Best-effort."""
    if not model:
        return {"ok": False, "error": "no model"}
    try:
        import ollama
        ollama.generate(model=model, prompt="", keep_alive=0)
        return {"ok": True, "unloaded": model}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def status() -> dict:
    """Full routing picture — what's installed, what's chosen, what's wrong."""
    models = installed_models()
    profiles = [{"model": m, "gb": _profile(m)[0], "quality": _profile(m)[1],
                 "vision": _is_vision(m)} for m in models]
    picks = {t: pick(t) for t in ("chat", "proposal", "planning", "vision")}
    warnings = [p["warning"] for p in picks.values() if p.get("warning")]
    return {"installed": profiles, "free_ram_gb": round(free_ram_gb(), 1),
            "picks": picks, "warnings": sorted(set(warnings)),
            "healthy": not warnings}
