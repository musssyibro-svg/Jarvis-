"""
services/model_router.py — pick the right model for the job.

Small formalisation of what was scattered across deepseek_service: route by task
class so we stop paying deepseek-r1's slow <think> tax for things a 1.5B model
does fine, and reserve the vision model for actual images.

    chat / proposal / routing / reflection  -> fast   (qwen2.5:1.5b class)
    hard planning / complex reasoning        -> reasoning
    screen understanding                     -> vision (llava)

Also exposes unload(model) so callers can free a heavy model from Ollama RAM
after a one-off use (the 16GB-machine concern) — best-effort, never fatal.
"""

TASK_CLASS = {
    "chat":       "fast",
    "proposal":   "fast",
    "routing":    "fast",
    "reflection": "fast",
    "summary":    "fast",
    "planning":   "reasoning",
    "reasoning":  "reasoning",
    "vision":     "vision",
}


def pick(task: str) -> dict:
    """Return {role, model} for a task class."""
    role = TASK_CLASS.get(task, "fast")
    try:
        from services.ollama_manager import resolve_models
        info = resolve_models()
        model = info.get("resolved", {}).get(role) or (info.get("installed") or [None])[0]
    except Exception:
        model = None
    return {"task": task, "role": role, "model": model}


def unload(model: str) -> dict:
    """Ask Ollama to drop a model from memory (keep_alive=0). Best-effort."""
    if not model:
        return {"ok": False, "error": "no model"}
    try:
        import ollama
        ollama.generate(model=model, prompt="", keep_alive=0)
        return {"ok": True, "unloaded": model}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def status() -> dict:
    return {task: pick(task) for task in ("chat", "planning", "vision")}
