# Jarvis V9 — Agent Extensibility Report

## 1. Registry design
agents/registry.py provides AgentRegistry with:
- register(name, agent, metadata) -> stores {instance, metadata, enabled}
- get(name) -> instance if registered AND enabled, else None
- list_agents() / enable(name, on) / health_check(name)

Module singleton `registry`; register_core_agents() wires the 6 built-ins
(desktop, browser, executor, perception, scout, proposal).

Metadata schema (MCP-compatible):
  name, permissions[], source (internal|MCP|plugin), health_status,
  registered_at. Extra keys pass through.

## 2. Agent lifecycle contract
Every agent SHOULD expose (duck-typed; registry tolerates absence):
  initialize()          -> prepare resources
  health_check()        -> "ok" | status string  (called by registry.health_check)
  execute(context)      -> standard invocation entry (OrchestratorCore uses this)
  shutdown()            -> release resources
Native agents today expose run()/observe()/_act(); the execute(context) contract
is the forward-looking uniform entry. Adapter shims can map execute->run during
transition without breaking callers.

## 3. How future agents are added (hooks only; deferred now)
registry.install_from_python(path)   - local .py
registry.install_from_zip(path)      - packaged agent
registry.install_from_git(url)       - clone + load
registry.install_from_manifest(url)  - manifest (incl. MCP descriptor)
registry.register_mcp_server(name, endpoint, permissions) - external MCP server
All return {"ok": False, "deferred": ...} today. Signatures are stable so
implementation later needs no caller changes.

## 4. Backend hooks needed for Settings -> Agents (future)
- GET  /agents/registry          -> list_agents() with metadata + enabled + health
- POST /agents/registry/{name}/enable {on: bool}  -> registry.enable
- POST /agents/registry/install  {source, location}  -> install_from_* dispatch
- POST /agents/registry/mcp      {name, endpoint, permissions} -> register_mcp_server
- GET  /agents/registry/{name}/health -> registry.health_check
(None implemented yet — listed so the Settings page has a defined contract.)

## 5. OrchestratorCore dispatch rule
Target pattern (no hardcoded specialist dispatch):
    agent = registry.get(task_type)
    if agent: agent.execute(context)
MCP agents resolve through the SAME registry.get() path, so OrchestratorCore
treats them identically to native agents. Migrating the current explicit handler
calls (_scout/_propose/_execute) to registry.get() is a Stage-2 refactor; the
registry + metadata + lifecycle contract needed for it exist now.

## 6. Chat-first invocation (future)
"Use QQ agent to message Alice" -> CommanderAdapter intent detection resolves an
agent name -> registry.get("qq") -> agent.execute({...}). The adapter is already
the single chat entry, so this needs only an agent-name intent rule later.

## Status
Hooks and architecture are in place and verified (core agents register, lookup
works, MCP-compatible metadata present, hooks deferred). No MCP integration,
no plugin installation, no Settings UI built — exactly as scoped.
