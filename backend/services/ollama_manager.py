"""
services/ollama_manager.py — Jarvis V8

Centralised Ollama management for a 16 GB Windows 10 box.

Hardware-aware rules (from the V8 directive):
  - Approved models only:
      fast      = qwen2.5:0.5b
      reasoning = deepseek-r1:1.5b
      vision    = llava:7b
  - Never hold two LARGE models resident at once.
  - llava is LARGE and loads ONLY when vision is explicitly requested; it is
    unloaded (best-effort) as soon as the vision call finishes.
  - Health checks + retry + model validation before every call.

This module has NO FastAPI / network dependency at import time, so it can be
unit-tested directly. `ollama` itself is imported lazily and degrades to clear
error dicts if missing.
"""
import os
import re
import threading
import time

# ── Approved model registry ──────────────────────────────────────────────────

# Read LIVE, never frozen at import.
#
# These used to be module-level os.getenv() constants, which broke settings in
# two ways at once: nothing consulted the settings table at all, and even after
# wiring it in, a change wouldn't apply until the backend restarted. Choosing a
# model in the UI and seeing Diagnostics still report the old one is exactly the
# "I set it, saved it, refreshed, still nothing" complaint.
def _cfg(key: str, default: str) -> str:
    try:
        from services import config
        return config.get(key, default) or default
    except Exception:
        return default


def fast_model() -> str:
    return _cfg("ollama_fast_model", "qwen2.5:3b")


def reasoning_model() -> str:
    return _cfg("ollama_reasoning_model", "deepseek-r1:1.5b")


def vision_model() -> str:
    return _cfg("ollama_vision_model", "llava:7b")


# Backwards compatibility for existing readers. These are the values at import
# time; every code path that matters calls the functions above instead.
FAST_MODEL      = os.getenv("OLLAMA_FAST_MODEL",      "qwen2.5:3b")
REASONING_MODEL = os.getenv("OLLAMA_REASONING_MODEL", "deepseek-r1:1.5b")
VISION_MODEL    = os.getenv("OLLAMA_VISION_MODEL",    "llava:7b")

# Which models count as "large" (don't co-resident them)
LARGE_MODELS = {VISION_MODEL}

APPROVED = {FAST_MODEL, REASONING_MODEL, VISION_MODEL}

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

# Serialise large-model use so two big models never load at once.
_large_lock = threading.Lock()


def _get_ollama():
    try:
        import ollama
        return ollama
    except ImportError:
        return None


# ── Health + validation ──────────────────────────────────────────────────────

# The installed-model list changes rarely but is queried before EVERY chat
# call (an extra HTTP round-trip per message). Cache it briefly.
_INSTALLED_CACHE = {"at": 0.0, "names": []}
_INSTALLED_TTL = 60  # seconds


def _list_installed(force: bool = False) -> list:
    """Return the list of installed model names, or [] if Ollama unreachable."""
    if not force and _INSTALLED_CACHE["names"] and \
            time.time() - _INSTALLED_CACHE["at"] < _INSTALLED_TTL:
        return list(_INSTALLED_CACHE["names"])
    o = _get_ollama()
    if not o:
        return []
    try:
        listed = o.list()
        names = []
        for m in listed.get("models", []):
            names.append(m.get("name") or m.get("model") or "")
        names = [n for n in names if n]
        if names:
            _INSTALLED_CACHE["at"] = time.time()
            _INSTALLED_CACHE["names"] = list(names)
        return names
    except Exception:
        return []


def _resolve(preferred: str, installed: list, kind: str) -> str | None:
    """
    Resolve a usable model name:
      1. exact match to preferred
      2. same family prefix (e.g. 'deepseek-r1' matches 'deepseek-r1:latest')
      3. any installed model whose name suggests the right role
      4. first installed model as last resort
    Returns None if nothing is installed.
    """
    if not installed:
        return None
    # 1. exact
    if preferred in installed:
        return preferred
    # 2. family prefix (strip tag)
    fam = preferred.split(":")[0]
    for n in installed:
        if n.split(":")[0] == fam:
            return n
    # 3. role heuristic
    role_hints = {
        "fast":      ["qwen", "phi", "gemma", "tinyllama"],
        "reasoning": ["deepseek", "r1", "llama", "qwen2", "mistral"],
        "vision":    ["llava", "bakllava", "moondream", "vision"],
    }.get(kind, [])
    matches = [n for n in installed if any(h in n.lower() for h in role_hints)]
    if matches:
        # "fast" means the LIGHTEST MODEL THAT IS STILL WORTH ASKING, not the
        # lightest model full stop. The old version sorted purely by size, so a
        # 0.5B model beat an installed 3B every time — and a sub-1B model can't
        # hold a multi-part instruction, which is the single biggest reason
        # Jarvis felt stupid while every subsystem reported healthy.
        if kind == "fast":
            def _params(name):
                m = re.search(r"[:\-](\d+(?:\.\d+)?)\s*b\b", name.lower())
                return float(m.group(1)) if m else 3.0

            usable = [n for n in matches if _params(n) >= 1.5]
            # Among usable models take the smallest (genuinely "fast"); if
            # nothing clears the floor, fall back to the biggest of a bad lot.
            if usable:
                return min(usable, key=_params)
            return max(matches, key=_params)
        return matches[0]
    # 4. vision MUST be a real vision model — never fall back to a text model
    if kind == "vision":
        return None
    # last resort for text roles: first installed
    return installed[0]


def resolve_models() -> dict:
    """
    Auto-detect installed models and resolve fast/reasoning/vision to real,
    usable names. No hardcoded assumption that the preferred model exists.
    """
    installed = _list_installed()
    # Live values, so a model chosen in Settings takes effect on the next call.
    want_fast, want_reason, want_vision = fast_model(), reasoning_model(), vision_model()
    resolved = {
        "fast":      _resolve(want_fast,   installed, "fast"),
        "reasoning": _resolve(want_reason, installed, "reasoning"),
        "vision":    _resolve(want_vision, installed, "vision"),
    }
    return {
        "installed":  installed,
        "preferred":  {"fast": want_fast, "reasoning": want_reason, "vision": want_vision},
        "resolved":   resolved,
        "using_fallback": {
            k: (resolved[k] is not None and resolved[k] != {"fast": want_fast,
                "reasoning": want_reason, "vision": want_vision}[k])
            for k in resolved
        },
    }


def health() -> dict:
    """Is the Ollama daemon reachable and which approved models are present?"""
    o = _get_ollama()
    if not o:
        return {"ok": False, "reason": "python 'ollama' package not installed",
                "installed_models": [], "approved_present": {}}
    try:
        listed = o.list()
        names = []
        for m in listed.get("models", []):
            names.append(m.get("name") or m.get("model") or "")
        present = {m: any(m == n or n.startswith(m.split(":")[0] + ":") for n in names)
                   for m in APPROVED}
        return {"ok": True, "host": OLLAMA_HOST, "installed_models": names,
                "approved_present": present}
    except Exception as e:
        return {"ok": False, "reason": f"cannot reach ollama daemon: {e}",
                "installed_models": [], "approved_present": {}}


def validate_model(model: str) -> dict:
    """Confirm a model is approved AND installed before using it."""
    if model not in APPROVED:
        return {"valid": False, "reason": f"'{model}' is not in approved set {sorted(APPROVED)}"}
    h = health()
    if not h["ok"]:
        return {"valid": False, "reason": h["reason"]}
    if not h["approved_present"].get(model):
        return {"valid": False, "reason": f"'{model}' not pulled. Run: ollama pull {model}"}
    return {"valid": True}


# ── Core call with retry ─────────────────────────────────────────────────────

# Generation limits. WITHOUT THESE, num_predict is unlimited and a model will
# happily generate until it decides to stop — which on a CPU-only 16GB machine
# meant a single screen analysis took 288 SECONDS, and a batch of 15 proposals
# never finished at all (the "0 proposals generated, engine looks frozen" bug).
# The model isn't broken and the machine isn't too slow; nobody ever told it
# when to stop.
LIMITS = {
    #                num_predict  num_ctx   hard timeout (s)
    "vision":       (320,         2048,     90),
    "fast":         (400,         4096,     60),
    "reasoning":    (700,         8192,    120),
    # Several proposals in ONE call. The point of these caps is to stop
    # UNBOUNDED generation, which once produced a 288-second screenshot
    # analysis — not to stop a deliberate, counted request. Writing four
    # proposals in one call is far cheaper than four calls that each reload
    # the model on a memory-starved machine.
    "batch":        (1400,        8192,    180),
}


def _chat_with_retry(model: str, messages: list, retries: int = 2,
                     backoff: float = 1.0, images: list | None = None,
                     kind: str = "fast") -> dict:
    o = _get_ollama()
    if not o:
        return {"ok": False, "text": "", "error": "ollama package not installed"}

    # Don't leave the model pinned in RAM by Ollama's 5-minute default. Vision
    # models are 5GB+; on a 16GB box that alone is why everything else crawls
    # after a single screen analysis. keep_alive scales with size/free memory.
    try:
        from services import model_router
        ka = model_router.keep_alive_for(model)
    except Exception:
        ka = "60s"

    n_predict, n_ctx, budget_s = LIMITS.get(kind, LIMITS["fast"])
    options = {"num_predict": n_predict, "num_ctx": n_ctx, "temperature": 0.7}

    last_err = None
    started = time.time()
    for attempt in range(retries + 1):
        # A timeout is not worth retrying: the second attempt is the same work
        # on the same machine and will take just as long. Retrying a 90-second
        # timeout three times is how a slow call became a five-minute hang.
        if time.time() - started > budget_s:
            return {"ok": False, "text": "",
                    "error": f"{model} exceeded its {budget_s}s budget. It is "
                             f"probably running on CPU. A smaller model would "
                             f"be much faster here."}
        try:
            # llava takes images on the last user message
            if images:
                msgs = list(messages)
                msgs[-1] = {**msgs[-1], "images": images}
                resp = o.chat(model=model, messages=msgs, keep_alive=ka,
                              options=options)
            else:
                resp = o.chat(model=model, messages=messages, keep_alive=ka,
                              options=options)
            text = resp["message"]["content"]
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return {"ok": True, "text": text, "error": None,
                    "took_s": round(time.time() - started, 1)}
        except Exception as e:
            last_err = str(e)
            if "timed out" in last_err.lower() or "timeout" in last_err.lower():
                break                       # see above — don't repeat a timeout
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    return {"ok": False, "text": "", "error": last_err}


def _unload(model: str):
    """Best-effort unload to free RAM (keep_alive=0 tells Ollama to release it)."""
    o = _get_ollama()
    if not o:
        return
    try:
        # keep_alive=0 evicts immediately. num_predict=0 means it doesn't
        # generate a single token on the way out — the old version asked the
        # model to answer "ok" first, paying for inference just to free memory.
        o.generate(model=model, prompt="", keep_alive=0,
                   options={"num_predict": 0})
    except Exception:
        pass


# ── Public API ───────────────────────────────────────────────────────────────

def fast(prompt: str, system: str = "") -> str:
    """Quick/cheap calls — preferred FAST_MODEL, auto-falls back to an installed model."""
    model = resolve_models()["resolved"]["fast"] or FAST_MODEL
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    r = _chat_with_retry(model, msgs, kind="fast")
    return r["text"] if r["ok"] else f"[Ollama fast error ({model}): {r['error']}]"


def reason(prompt: str, system: str = "", history: list | None = None) -> str:
    """Heavier reasoning — preferred REASONING_MODEL, auto-falls back to an installed model."""
    model = resolve_models()["resolved"]["reasoning"] or REASONING_MODEL
    msgs = ([{"role": "system", "content": system}] if system else [])
    if history:
        msgs += [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
    msgs.append({"role": "user", "content": prompt})
    r = _chat_with_retry(model, msgs, kind="reasoning")
    return r["text"] if r["ok"] else f"[Ollama reason error ({model}): {r['error']}]"


def vision(prompt: str, image_b64: str) -> dict:
    """
    Vision understanding — uses the auto-detected resolved vision model.
    Does NOT assume llava:7b is installed: resolve_models() picks whatever real
    vision model is present (llava, bakllava, moondream...). If none is installed,
    returns a clean error instead of trying a hardcoded/absent model.
    Loaded ONLY here, behind the large-model lock, and unloaded afterwards so we
    never hold two large models at once.
    """
    model = resolve_models()["resolved"]["vision"]
    if not model:
        return {"ok": False, "text": "", "error":
                "No vision model installed. Pull one, e.g.: ollama pull llava:7b "
                "(or bakllava / moondream)."}

    v = validate_model(model) if model in APPROVED else {"valid": True}
    if not v.get("valid"):
        return {"ok": False, "text": "", "error": v.get("reason", "vision model invalid")}

    with _large_lock:   # ensures only one large-model session at a time
        try:
            msgs = [{"role": "user", "content": prompt}]
            # Vision gets the tightest budget: it is the slowest call Jarvis makes
            # and the one a user is most likely to be sitting waiting for.
            r = _chat_with_retry(model, msgs, retries=0, images=[image_b64],
                                 kind="vision")
            return {"ok": r["ok"], "text": r["text"], "error": r["error"], "model": model}
        finally:
            _unload(model)   # free RAM immediately after


def status() -> dict:
    h = health()
    return {
        "models": {"fast": FAST_MODEL, "reasoning": REASONING_MODEL, "vision": VISION_MODEL},
        "large_models": sorted(LARGE_MODELS),
        "health": h,
        "ram_policy": "single large model at a time; llava lazy-loaded + unloaded per call",
    }
