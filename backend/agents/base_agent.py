"""agents/base_agent.py — Base class for all Jarvis agents"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("jarvis.agents")

class BaseAgent:
    name: str = "base"

    def log(self, msg: str, level: str = "info"):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{self.name.upper()}] {msg}"
        getattr(logger, level, logger.info)(entry)
        return {"ts": ts, "agent": self.name, "msg": msg}

    def run(self, context: dict) -> dict:
        raise NotImplementedError
