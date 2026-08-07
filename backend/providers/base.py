"""
providers/base.py — what every AI provider must be able to do.

The router talks to providers only through this interface, so adding Gemini or
swapping Ollama for something else never touches a single line of Jarvis's
actual behaviour. Four methods, deliberately: anything richer would leak a
particular provider's shape into the router and defeat the point.

TWO RULES FOR IMPLEMENTORS

  1. NEVER RAISE for an expected failure. A missing key, an unreachable host, a
     model that isn't pulled — all of those return a readable string beginning
     with "[". Callers all over Jarvis pass this straight to the user, and an
     exception escaping here turns "the model isn't installed" into a 500.

  2. SAY WHY in health(). "ok: false" on its own sends someone hunting. The
     reason is what makes it fixable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator


class Provider(ABC):
    """One place Jarvis can send a prompt."""

    name: str = "abstract"

    @abstractmethod
    def chat(self, messages: list[dict], model: str | None = None,
             temperature: float = 0.7, max_tokens: int | None = None,
             task: str = "", timeout: float | None = None, **kwargs) -> str:
        """One complete answer as a string. Errors come back as '[...]' text."""

    @abstractmethod
    def stream(self, messages: list[dict], model: str | None = None,
               temperature: float = 0.7, max_tokens: int | None = None,
               task: str = "", timeout: float | None = None,
               **kwargs) -> Generator[str, None, None]:
        """Yield text chunks as they arrive."""

    @abstractmethod
    def health(self) -> dict:
        """{ok, reason, models} — reason is required when ok is False."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """What this provider can run right now."""

    def select_model(self, task: str = "", fast: bool = False) -> str | None:
        """
        Which model for this task. Overridden by providers that have real
        choices to make; the default is 'whatever there is'.
        """
        models = self.list_models()
        return models[0] if models else None

    def configured(self) -> bool:
        """Is this worth trying at all? Skipped in the chain when False."""
        return True
