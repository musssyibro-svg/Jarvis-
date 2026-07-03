"""
agents/registry.py — Agent Registry (V9 hooks only).

Purpose: let OrchestratorCore look agents up by task_type instead of hardcoding
specialist dispatch. Designed MCP-compatible so external tool-backed agents
(Playwright MCP, Firecrawl MCP, custom QQ agent) can register later WITHOUT a
refactor. MCP integration itself is NOT implemented here — only the hooks.

This is intentionally minimal: registration + lookup + lifecycle contract +
extensibility hook signatures. No plugin installation, no Settings UI.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("jarvis.registry")


def _now():
    return datetime.now(timezone.utc).isoformat()


class AgentRegistry:
    def __init__(self):
        self.agents = {}

    def register(self, name: str, agent, metadata: dict | None = None) -> dict:
        meta = {
            "name":          name,
            "permissions":   (metadata or {}).get("permissions", []),
            "source":        (metadata or {}).get("source", "internal"),  # internal|MCP|plugin
            "health_status": "unknown",
            "registered_at": _now(),
            **(metadata or {}),
        }
        self.agents[name] = {"instance": agent, "metadata": meta, "enabled": True}
        return self.agents[name]

    def get(self, name: str):
        entry = self.agents.get(name)
        if not entry or not entry["enabled"]:
            return None
        return entry["instance"]

    def list_agents(self) -> dict:
        return self.agents

    def enable(self, name: str, on: bool = True) -> bool:
        if name in self.agents:
            self.agents[name]["enabled"] = on
            return True
        return False

    def health_check(self, name: str) -> dict:
        entry = self.agents.get(name)
        if not entry:
            return {"name": name, "health_status": "missing"}
        inst = entry["instance"]
        status = "ok"
        if hasattr(inst, "health_check"):
            try:
                status = inst.health_check() or "ok"
            except Exception as e:
                status = f"error: {e}"
        entry["metadata"]["health_status"] = status
        return {"name": name, "health_status": status,
                "source": entry["metadata"]["source"], "enabled": entry["enabled"]}

    # ── Extensibility hooks (signatures only — future, not implemented now) ──────
    def install_from_python(self, path: str) -> dict:
        """FUTURE: load an agent from a local .py file. Hook only."""
        return {"ok": False, "deferred": "install_from_python not implemented (Stage 2+)"}

    def install_from_zip(self, path: str) -> dict:
        """FUTURE: load an agent package from a ZIP. Hook only."""
        return {"ok": False, "deferred": "install_from_zip not implemented (Stage 2+)"}

    def install_from_git(self, url: str) -> dict:
        """FUTURE: clone+load an agent from a Git URL. Hook only."""
        return {"ok": False, "deferred": "install_from_git not implemented (Stage 2+)"}

    def install_from_manifest(self, url: str) -> dict:
        """FUTURE: load an agent (incl. MCP server) from a manifest URL. Hook only."""
        return {"ok": False, "deferred": "install_from_manifest not implemented (Stage 2+)"}

    def register_mcp_server(self, name: str, endpoint: str, permissions: list | None = None) -> dict:
        """
        FUTURE hook: register an external MCP server as a tool-backed agent.
        Returns deferred now; signature is stable so OrchestratorCore can treat
        MCP agents exactly like native agents via get(name) once implemented.
        """
        return {"ok": False, "deferred": "MCP integration not implemented (by design)",
                "would_register": {"name": name, "endpoint": endpoint,
                                   "source": "MCP", "permissions": permissions or []}}


# Module singleton + core-agent registration
registry = AgentRegistry()


def register_core_agents():
    """Register the built-in specialists so OrchestratorCore can look them up."""
    try:
        from agents import desktop_agent
        registry.register("desktop", desktop_agent,
                          {"source": "internal", "permissions": ["desktop.control"]})
    except Exception as e:
        logger.warning(f"register_core_agents: 'desktop' registration failed: {e}")
    try:
        from agents.browser_agent import BrowserAgent
        registry.register("browser", BrowserAgent,
                          {"source": "internal", "permissions": ["browser.control"]})
    except Exception as e:
        logger.warning(f"register_core_agents: 'browser' registration failed: {e}")
    try:
        from agents.executor_agent import ExecutorAgent
        registry.register("executor", ExecutorAgent,
                          {"source": "internal", "permissions": ["execute"]})
    except Exception as e:
        logger.warning(f"register_core_agents: 'executor' registration failed: {e}")
    try:
        from agents.perception_agent import perception
        registry.register("perception", perception,
                          {"source": "internal", "permissions": ["screen.read"]})
    except Exception as e:
        logger.warning(f"register_core_agents: 'perception' registration failed: {e}")
    try:
        from agents.scout_agent import ScoutAgent
        registry.register("scout", ScoutAgent,
                          {"source": "internal", "permissions": ["web.scan"]})
    except Exception as e:
        logger.warning(f"register_core_agents: 'scout' registration failed: {e}")
    try:
        from agents.proposal_agent import ProposalAgent
        registry.register("proposal", ProposalAgent,
                          {"source": "internal", "permissions": ["llm.generate"]})
    except Exception as e:
        logger.warning(f"register_core_agents: 'proposal' registration failed: {e}")
    return registry.list_agents()
