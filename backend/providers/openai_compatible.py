"""
providers/openai_compatible.py — one provider for every cloud model worth using.

ONE FILE, NOT SIX. The obvious plan is a separate plugin per vendor —
deepseek_provider.py, glm_provider.py, kimi_provider.py, openrouter_provider.py,
omniroute_provider.py, together_provider.py. Every one of those would be the
same eighty lines with a different base URL, and six copies of the same code is
six places for the same bug to survive a fix.

They all speak the OpenAI chat-completions protocol:

    DeepSeek      https://api.deepseek.com/v1
    Zhipu / GLM   https://open.bigmodel.cn/api/paas/v4
    Moonshot/Kimi https://api.moonshot.cn/v1
    OpenRouter    https://openrouter.ai/api/v1
    Together      https://api.together.xyz/v1
    Google Gemini https://generativelanguage.googleapis.com/v1beta/openai
    OpenAI        https://api.openai.com/v1
    LM Studio     http://127.0.0.1:1234/v1
    vLLM / llama.cpp / OmniRoute — same shape

So this is one implementation parameterised by base URL, key and model. Adding a
vendor is three settings, not a file.

Built on `requests`, which Jarvis already depends on, rather than the `openai`
SDK — a whole package to POST one JSON body would be a dependency that earns
nothing, and every one of these endpoints is reachable from China except
OpenAI's, which is the one the user can't use anyway.

Nothing here is enabled by default. With no key configured the provider reports
itself unconfigured and the router skips it, so Jarvis stays fully local unless
the user deliberately says otherwise.
"""
from __future__ import annotations

import json
from typing import Generator

from providers.base import Provider

# Vendors worth naming, so the UI can offer them and the user doesn't have to
# go and find the URL. Anything not listed still works — set the base URL.
PRESETS: dict[str, dict] = {
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",
                   "model": "deepseek-chat", "label": "DeepSeek"},
    "glm":        {"base_url": "https://open.bigmodel.cn/api/paas/v4",
                   "model": "glm-4-flash", "label": "Zhipu GLM"},
    "kimi":       {"base_url": "https://api.moonshot.cn/v1",
                   "model": "moonshot-v1-8k", "label": "Moonshot / Kimi"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                   "model": "", "label": "OpenRouter (many models)"},
    "omniroute":  {"base_url": "", "model": "", "label": "OmniRoute"},
    "openai":     {"base_url": "https://api.openai.com/v1",
                   "model": "gpt-4o-mini", "label": "OpenAI"},
    "gemini":     {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                   "model": "gemini-2.0-flash", "label": "Google Gemini"},
    "lmstudio":   {"base_url": "http://127.0.0.1:1234/v1",
                   "model": "", "label": "LM Studio (local)"},
}


def _setting(key: str, default: str = "") -> str:
    try:
        from services import config
        return (config.get(key, default) or "").strip()
    except Exception:
        return default


class OpenAICompatible(Provider):
    """
    One configured endpoint. Reads three settings:

        ai_<name>_base_url    where to POST      (preset supplies a default)
        ai_<name>_api_key     the key            (no key -> not configured)
        ai_<name>_model       which model
    """

    def __init__(self, name: str = "openai"):
        self.name = name
        preset = PRESETS.get(name, {})
        self.base_url = (_setting(f"ai_{name}_base_url")
                         or preset.get("base_url", "")).rstrip("/")
        self.api_key = _setting(f"ai_{name}_api_key")
        self.model = _setting(f"ai_{name}_model") or preset.get("model", "")
        self.label = preset.get("label", name)

    # ── availability ─────────────────────────────────────────────────────────

    def configured(self) -> bool:
        if not self.base_url:
            return False
        # A local endpoint (LM Studio, vLLM) legitimately has no key.
        local = any(h in self.base_url for h in ("127.0.0.1", "localhost", "::1"))
        return bool(self.api_key or local)

    def health(self) -> dict:
        if not self.base_url:
            return {"ok": False, "models": [],
                    "reason": f"no address set — put one in ai_{self.name}_base_url"}
        if not self.configured():
            return {"ok": False, "models": [],
                    "reason": f"no API key — put one in ai_{self.name}_api_key"}
        try:
            models = self.list_models()
        except Exception as e:
            return {"ok": False, "models": [],
                    "reason": f"{self.base_url} didn't answer: {str(e)[:90]}"}
        return {"ok": True, "reason": "", "models": models[:20]}

    # ── talking to it ────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, messages, model=None, temperature=0.7, max_tokens=None,
             task="", timeout=None, **kwargs) -> str:
        if not self.configured():
            return f"[{self.label} isn't set up — no API key]"
        import requests
        model = model or self.model
        if not model:
            return (f"[{self.label}: no model chosen. Set ai_{self.name}_model "
                    f"in Settings.]")
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={"model": model, "messages": messages,
                      "temperature": temperature,
                      "max_tokens": max_tokens or 800},
                timeout=timeout or 90,
            )
        except Exception as e:
            return f"[{self.label} unreachable: {str(e)[:120]}]"
        if r.status_code == 401:
            return f"[{self.label} rejected the API key. Check ai_{self.name}_api_key.]"
        if r.status_code == 429:
            return f"[{self.label} is rate-limiting or out of credit.]"
        if r.status_code >= 400:
            return f"[{self.label} error {r.status_code}: {r.text[:160]}]"
        try:
            data = r.json()
            return (data["choices"][0]["message"]["content"] or "").strip() \
                or f"[{self.label} returned nothing.]"
        except Exception as e:
            return f"[{self.label} sent something unexpected: {str(e)[:100]}]"

    def stream(self, messages, model=None, temperature=0.7, max_tokens=None,
               task="", timeout=None, **kwargs) -> Generator[str, None, None]:
        if not self.configured():
            yield f"[{self.label} isn't set up — no API key]"
            return
        import requests
        model = model or self.model
        if not model:
            yield f"[{self.label}: no model chosen.]"
            return
        try:
            with requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={"model": model, "messages": messages, "stream": True,
                          "temperature": temperature,
                          "max_tokens": max_tokens or 800},
                    timeout=timeout or 90, stream=True) as r:
                if r.status_code >= 400:
                    yield f"[{self.label} error {r.status_code}]"
                    return
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw or not raw.startswith("data:"):
                        continue
                    payload = raw[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        delta = json.loads(payload)["choices"][0].get("delta", {})
                    except Exception:
                        continue          # keep-alive or a partial frame
                    chunk = delta.get("content")
                    if chunk:
                        yield chunk
        except Exception as e:
            yield f"[{self.label} unreachable: {str(e)[:120]}]"

    def list_models(self) -> list[str]:
        if not self.configured():
            return []
        import requests
        r = requests.get(f"{self.base_url}/models", headers=self._headers(),
                         timeout=20)
        r.raise_for_status()
        return [m.get("id", "") for m in (r.json().get("data") or []) if m.get("id")]

    def select_model(self, task: str = "", fast: bool = False) -> str | None:
        return self.model or None


Provider = OpenAICompatible
