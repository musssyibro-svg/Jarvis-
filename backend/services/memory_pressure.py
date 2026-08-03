"""
services/memory_pressure.py — the number that explains almost everything.

On a 16 GB machine running Windows, Edge, QQ, a Playwright browser, a Python
backend and a local LLM, free RAM is the variable that decides whether Jarvis
feels instant or broken. At 92% used:

  * Ollama's first call takes 60–180 seconds instead of 3, because Windows is
    paging to disk. The console shows "Ollama offline" and the user reasonably
    concludes it's broken.
  * model_router correctly falls back to a 0.5B model, because nothing larger
    fits. Answers get noticeably worse.
  * Vision becomes unusable: llava:7b needs ~5 GB.

Three symptoms, one cause, and until now no screen said so. That is the actual
bug — not the RAM itself, which is a fact about the machine, but the silence
about it. Someone watching a spinner has no way to know the fix is "close some
Edge tabs".

This module makes it explicit: how much is free, what that means right now,
what is holding memory, and a button to get some back.
"""
from __future__ import annotations

# Thresholds tuned for THIS machine, not general advice. The 3 GB figure is the
# point below which qwen2.5:3b (~2.4 GB resident) stops fitting, which is the
# moment quality visibly drops.
GOOD_GB = 4.0
TIGHT_GB = 3.0
CRITICAL_GB = 2.0


def _free_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().available / 1e9
    except Exception:
        return 0.0


def _total_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1e9
    except Exception:
        return 0.0


def loaded_models() -> list[dict]:
    """
    What Ollama currently has resident. `ollama ps`, essentially.

    Best-effort: an older client may not expose ps(), and that's a missing
    detail rather than a failure — the rest of the report is still useful.
    """
    try:
        import ollama
        data = ollama.ps()
    except Exception:
        return []
    out = []
    for m in (data.get("models") or []):
        out.append({
            "name": m.get("model") or m.get("name") or "?",
            "gb": round((m.get("size") or 0) / 1e9, 1),
            "until": str(m.get("expires_at") or "")[:19],
        })
    return out


def hogs(limit: int = 6) -> list[dict]:
    """
    The biggest memory users, so "close some apps" names which ones.

    Jarvis's own processes are marked, because telling someone to close the
    thing they're using would be unhelpful, and because it's honest about
    Jarvis's own share.
    """
    try:
        import psutil
    except Exception:
        return []
    ours = {"python", "python3", "pythonw", "node", "ollama", "ollama_llama_server"}
    rows = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (p.info.get("name") or "").replace(".exe", "").lower()
            mem = (p.info.get("memory_info").rss if p.info.get("memory_info") else 0)
        except Exception:
            continue
        if not name or mem < 150e6:
            continue
        rows.append({"name": name, "gb": round(mem / 1e9, 2),
                     "is_jarvis": name in ours})
    # Group by name — Edge alone is a dozen processes, and a list of twelve
    # "msedge" rows tells you nothing you can act on.
    merged: dict[str, dict] = {}
    for r in rows:
        m = merged.setdefault(r["name"], {"name": r["name"], "gb": 0.0,
                                          "processes": 0,
                                          "is_jarvis": r["is_jarvis"]})
        m["gb"] = round(m["gb"] + r["gb"], 2)
        m["processes"] += 1
    return sorted(merged.values(), key=lambda x: x["gb"], reverse=True)[:limit]


def level(free: float | None = None) -> str:
    f = _free_gb() if free is None else free
    if f >= GOOD_GB:
        return "ok"
    if f >= TIGHT_GB:
        return "tight"
    if f >= CRITICAL_GB:
        return "low"
    return "critical"


def status() -> dict:
    """Everything needed to explain a slow Jarvis in one glance."""
    free, total = _free_gb(), _total_gb()
    lvl = level(free)
    used_pct = round((1 - free / total) * 100) if total else 0

    # What this level actually costs, in terms the user recognises.
    effects = {
        "ok": [],
        "tight": ["Vision (reading your screen) will be slow — it needs about 5 GB."],
        "low": ["Jarvis is using a smaller, weaker model because the good one "
                "doesn't fit.",
                "Reading your screen will be very slow or will time out."],
        "critical": ["Ollama's first answer may take a minute or more — Windows "
                     "is paging to disk. It is not offline, just starved.",
                     "Jarvis has fallen back to its smallest model, so answers "
                     "will be noticeably worse.",
                     "Reading your screen won't work."],
    }[lvl]

    big = [h for h in hogs() if not h["is_jarvis"]][:3]
    advice = []
    if lvl != "ok":
        if big:
            advice.append("Close what you're not using — biggest first: "
                          + ", ".join(f"{h['name']} ({h['gb']} GB)" for h in big))
        advice.append("Press \"Free up memory\" to unload the AI models Ollama "
                      "is holding. They reload automatically when needed.")

    return {
        "free_gb": round(free, 1),
        "total_gb": round(total, 1),
        "used_percent": used_pct,
        "level": lvl,
        "headline": {
            "ok": f"{round(free, 1)} GB free — plenty.",
            "tight": f"{round(free, 1)} GB free — getting tight.",
            "low": f"Only {round(free, 1)} GB free. This is why Jarvis feels slow.",
            "critical": f"Only {round(free, 1)} GB free. Jarvis isn't broken — "
                        f"it's out of memory.",
        }[lvl],
        "effects": effects,
        "advice": advice,
        "models_loaded": loaded_models(),
        "using_memory": hogs(),
    }


def free_now() -> dict:
    """
    Unload every resident model immediately.

    Ollama has no "unload everything" call, so each loaded model is asked for
    with keep_alive=0, which tells the server to drop it the moment that
    (deliberately trivial) request finishes.
    """
    before = round(_free_gb(), 1)
    loaded = loaded_models()
    if not loaded:
        return {"ok": True, "freed_gb": 0.0, "before_gb": before,
                "after_gb": before, "unloaded": [],
                "note": "Ollama wasn't holding any models — nothing to free. "
                        "The memory is going to other programs."}

    done, failed = [], []
    try:
        import ollama
    except Exception as e:
        return {"ok": False, "error": f"can't reach Ollama: {e}"}

    for m in loaded:
        try:
            ollama.chat(model=m["name"],
                        messages=[{"role": "user", "content": "."}],
                        keep_alive=0, options={"num_predict": 1})
            done.append(m["name"])
        except Exception:
            failed.append(m["name"])

    import time
    time.sleep(1.5)                    # the server needs a moment to actually free it
    after = round(_free_gb(), 1)
    return {
        "ok": True,
        "before_gb": before, "after_gb": after,
        "freed_gb": round(max(0.0, after - before), 1),
        "unloaded": done, "failed": failed,
        "note": (f"Released {len(done)} model(s). They reload automatically the "
                 f"next time Jarvis needs to think."
                 + (f" Couldn't release: {', '.join(failed)}." if failed else "")),
    }
