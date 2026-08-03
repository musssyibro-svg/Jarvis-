"""
providers/ollama_provider.py — the local models, behind the provider interface.

This WRAPS services/ollama_manager.py and services/model_router.py rather than
replacing them, and that is the whole design decision. Those two modules carry
a lot of hard-won, machine-specific knowledge:

    ollama_manager   per-kind token/context/timeout caps (an unbounded call
                     once produced a 288-second screenshot analysis), model
                     validation, keep_alive tuned for a 16 GB machine
    model_router     picks the strongest model that FITS IN FREE RAM right now,
                     which is why a 0.5B model correctly wins on a machine at
                     87% memory even with a 3B one installed

A "clean" rewrite would throw all of that away and rediscover it the hard way.
The provider's job is only to be the standard shape the router can talk to.

Division of labour, to keep it straight:

    ai_router      chooses the PROVIDER   (local? cloud? which cloud?)
    this provider  chooses the MODEL      (via model_router, RAM-aware)
"""
from __future__ import annotations

from typing import Generator

from providers.base import Provider


class OllamaProvider(Provider):
    name = "ollama"

    # Jarvis's task names -> the three roles ollama_manager understands.
    # Anything unlisted gets "fast", which is the right default on a machine
    # where the alternative is swapping.
    _KIND = {
        "vision": "vision",
        "reasoning": "reasoning",
        "planner": "reasoning",
        "coding": "reasoning",
        "proposal": "fast",
        "chat": "fast",
        "memory": "fast",
        "browser": "fast",
    }

    # ...and to the model_router's task vocabulary, which knows the minimum
    # quality each job actually needs.
    _ROUTER_TASK = {
        "chat": "chat", "proposal": "proposal", "memory": "summary",
        "reasoning": "reasoning", "planner": "planning", "coding": "reasoning",
        "vision": "vision", "browser": "chat",
    }

    def _client(self):
        try:
            import ollama
            return ollama
        except Exception:
            return None

    def configured(self) -> bool:
        return self._client() is not None

    def select_model(self, task: str = "", fast: bool = False) -> str | None:
        """
        Ask model_router, which weighs quality against the RAM that is free at
        this instant. Falling back to the configured name would reintroduce the
        exact bug that made Jarvis pick a model too big to run.
        """
        try:
            from services import model_router
            chosen = model_router.pick(self._ROUTER_TASK.get(task, "chat"))
            if chosen.get("model"):
                return chosen["model"]
        except Exception:
            pass
        # model_router unavailable: fall back to the configured role name.
        try:
            from services import ollama_manager
            kind = self._KIND.get(task, "fast")
            return {"fast": ollama_manager.fast_model,
                    "reasoning": ollama_manager.reasoning_model,
                    "vision": ollama_manager.vision_model}[kind]()
        except Exception:
            return None

    def _kind(self, task: str) -> str:
        return self._KIND.get(task, "fast")

    def chat(self, messages, model=None, temperature=0.7, max_tokens=None,
             task="", timeout=None, **kwargs) -> str:
        client = self._client()
        if client is None:
            return ("[Ollama isn't installed. Install it from ollama.com, then "
                    "run: ollama pull qwen2.5:3b]")
        model = model or self.select_model(task)
        if not model:
            return "[No Ollama model is available. Run: ollama pull qwen2.5:3b]"

        # Bounds come from ollama_manager, which knows what this machine can
        # take. Unbounded generation is not a theoretical risk here — it has
        # already cost this project a 288-second screen analysis.
        try:
            from services.ollama_manager import LIMITS, keep_alive_for
            cap_tokens, cap_ctx, cap_timeout = LIMITS.get(
                self._kind(task), LIMITS["fast"])
            keep = keep_alive_for(model)
        except Exception:
            cap_tokens, cap_ctx, cap_timeout, keep = 400, 4096, 60, "5m"

        try:
            resp = client.chat(
                model=model, messages=messages, keep_alive=keep,
                options={"num_predict": min(max_tokens or cap_tokens, cap_tokens),
                         "num_ctx": cap_ctx, "temperature": temperature},
            )
            text = (resp.get("message", {}) or {}).get("content", "") or ""
            return text.strip() or "[The model returned nothing.]"
        except Exception as e:
            return f"[Ollama error: {e}]"

    def stream(self, messages, model=None, temperature=0.7, max_tokens=None,
               task="", timeout=None, **kwargs) -> Generator[str, None, None]:
        client = self._client()
        if client is None:
            yield "[Ollama isn't installed. Install it from ollama.com.]"
            return
        model = model or self.select_model(task)
        if not model:
            yield "[No Ollama model is available. Run: ollama pull qwen2.5:3b]"
            return
        try:
            from services.ollama_manager import LIMITS, keep_alive_for
            cap_tokens, cap_ctx, _ = LIMITS.get(self._kind(task), LIMITS["fast"])
            keep = keep_alive_for(model)
        except Exception:
            cap_tokens, cap_ctx, keep = 400, 4096, "5m"
        try:
            for part in client.chat(
                    model=model, messages=messages, stream=True, keep_alive=keep,
                    options={"num_predict": min(max_tokens or cap_tokens, cap_tokens),
                             "num_ctx": cap_ctx, "temperature": temperature}):
                chunk = (part.get("message", {}) or {}).get("content", "")
                if chunk:
                    yield chunk
        except Exception as e:
            yield f"[Ollama error: {e}]"

    def health(self) -> dict:
        client = self._client()
        if client is None:
            return {"ok": False, "reason": "the ollama python package isn't installed",
                    "models": []}
        try:
            models = self.list_models()
        except Exception as e:
            return {"ok": False,
                    "reason": f"Ollama isn't answering ({str(e)[:80]}). "
                              f"Start it with: ollama serve",
                    "models": []}
        if not models:
            return {"ok": False, "reason": "running, but no models are pulled. "
                                           "Run: ollama pull qwen2.5:3b",
                    "models": []}
        return {"ok": True, "reason": "", "models": models}

    def list_models(self) -> list[str]:
        client = self._client()
        if client is None:
            return []
        data = client.list()
        return [m.get("model") or m.get("name") or ""
                for m in (data.get("models") or [])
                if (m.get("model") or m.get("name"))]


Provider = OllamaProvider          # what the router looks for
