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

    # ── Custom agent installation (drop a .py file / paste code → live agent) ───

    def install_from_code(self, name: str, code: str, description: str = "") -> dict:
        """
        Register a custom agent from Python source. The code must define either
        a class with a run(context)->dict method, or a module-level
        run(context)->dict function. Saved to agents/custom/<name>.py,
        persisted in the DB, loaded immediately, and visible in the UI.
        """
        import re
        name = (name or "").strip().lower().replace(" ", "_")
        if not re.fullmatch(r"[a-z_][a-z0-9_]{1,40}", name or ""):
            return {"ok": False, "error": "name must be a valid identifier "
                    "(letters, digits, underscore; 2-41 chars)"}
        if name in self.agents and self.agents[name]["metadata"].get("source") == "internal":
            return {"ok": False, "error": f"'{name}' is a built-in agent — pick another name"}
        try:
            compile(code, f"<agent:{name}>", "exec")
        except SyntaxError as e:
            return {"ok": False, "error": f"syntax error in agent code: {e}"}

        custom_dir = _custom_dir()
        path = custom_dir / f"{name}.py"
        path.write_text(code, encoding="utf-8")
        try:
            instance, kind = _load_agent_instance(name, path)
        except Exception as e:
            path.unlink(missing_ok=True)
            return {"ok": False, "error": f"agent failed to load: {e}"}

        self.register(name, instance, {"source": "custom", "description": description,
                                       "kind": kind, "path": str(path)})
        _persist_custom(name, path.name, description, enabled=True)
        logger.info(f"registry: installed custom agent '{name}' ({kind})")
        return {"ok": True, "name": name, "kind": kind, "path": str(path)}

    def install_from_python(self, path: str) -> dict:
        """Load an agent from an existing local .py file."""
        from pathlib import Path as _P
        p = _P(path)
        if not p.exists() or p.suffix != ".py":
            return {"ok": False, "error": f"not a .py file: {path}"}
        return self.install_from_code(p.stem, p.read_text(encoding="utf-8"),
                                      description=f"installed from {p.name}")

    def uninstall(self, name: str) -> dict:
        entry = self.agents.get(name)
        if not entry or entry["metadata"].get("source") != "custom":
            return {"ok": False, "error": f"'{name}' is not a custom agent"}
        self.agents.pop(name, None)
        try:
            from models.db import conn
            with conn() as db:
                db.execute("DELETE FROM custom_agents WHERE name=?", (name,))
        except Exception:
            pass
        try:
            from pathlib import Path as _P
            p = _P(entry["metadata"].get("path", ""))
            if p.exists():
                p.unlink()
        except Exception:
            pass
        return {"ok": True, "removed": name}

    def run_agent(self, name: str, context: dict) -> dict:
        inst = self.get(name)
        if inst is None:
            return {"ok": False, "error": f"agent '{name}' not found or disabled"}
        runner = inst.run if hasattr(inst, "run") else inst
        try:
            result = runner(context or {})
            return {"ok": True, "agent": name, "result": result}
        except Exception as e:
            return {"ok": False, "agent": name, "error": str(e)}

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


# ── Custom-agent plumbing ─────────────────────────────────────────────────────

CUSTOM_SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_agents (
    name        TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    description TEXT,
    enabled     INTEGER DEFAULT 1,
    created_at  TEXT
);
"""


def _custom_dir():
    from pathlib import Path
    d = Path(__file__).resolve().parent / "custom"
    d.mkdir(exist_ok=True)
    init = d / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")
    return d


def _load_agent_instance(name: str, path):
    """Import the file and return (instance_with_run, kind)."""
    import importlib.util
    import inspect
    spec = importlib.util.spec_from_file_location(f"agents.custom.{name}", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 1) a class defining run(context)
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ == module.__name__ and callable(getattr(cls, "run", None)):
            return cls(), f"class {cls.__name__}"
    # 2) a module-level run(context) function
    fn = getattr(module, "run", None)
    if callable(fn):
        agent_name = name
        class _FnAgent:
            name = agent_name
            def run(self, context: dict) -> dict:
                return fn(context)
        return _FnAgent(), "function run()"
    raise ValueError("no class with run(context) and no run(context) function found")


def _persist_custom(name: str, filename: str, description: str, enabled: bool):
    try:
        from models.db import conn
        with conn() as db:
            db.executescript(CUSTOM_SCHEMA)
            db.execute("INSERT OR REPLACE INTO custom_agents"
                       "(name,filename,description,enabled,created_at) VALUES(?,?,?,?,?)",
                       (name, filename, description, 1 if enabled else 0, _now()))
    except Exception as e:
        logger.warning(f"registry: could not persist custom agent '{name}': {e}")


AGENT_TEMPLATE = '''"""Custom Jarvis agent. It receives a context dict and returns a dict."""

class MyAgent:
    name = "my_agent"

    def run(self, context: dict) -> dict:
        # Your logic here. You can import Jarvis internals, e.g.:
        #   from agents import desktop_agent
        #   desktop_agent.open_app("notepad")
        message = context.get("message", "hello")
        return {"ok": True, "echo": message}
'''


def load_custom_agents() -> int:
    """Reload all persisted custom agents at startup. Returns count loaded."""
    loaded = 0
    try:
        from models.db import conn
        with conn() as db:
            db.executescript(CUSTOM_SCHEMA)
            rows = db.execute("SELECT * FROM custom_agents").fetchall()
    except Exception as e:
        logger.warning(f"registry: custom agent table unavailable: {e}")
        return 0
    d = _custom_dir()
    for r in rows:
        path = d / r["filename"]
        if not path.exists():
            logger.warning(f"registry: custom agent file missing: {path}")
            continue
        try:
            instance, kind = _load_agent_instance(r["name"], path)
            registry.register(r["name"], instance,
                              {"source": "custom", "kind": kind,
                               "description": r["description"] or "",
                               "path": str(path)})
            registry.enable(r["name"], bool(r["enabled"]))
            loaded += 1
        except Exception as e:
            logger.warning(f"registry: failed to load custom agent '{r['name']}': {e}")
    if loaded:
        logger.info(f"registry: {loaded} custom agent(s) loaded")
    return loaded


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
