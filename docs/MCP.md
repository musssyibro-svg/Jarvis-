# MCP

`backend/mcp_server.py`

A second door into Jarvis, so Claude Desktop, Cherry Studio, Cline, Chatbox or
Open WebUI can drive it. **Jarvis stays the brain.** These clients are
additional, disposable and swappable; nothing about Jarvis changes to
accommodate them.

Optional. `START.bat` does not run it.

```
python backend/mcp_server.py            # stdio, for Claude Desktop
python backend/mcp_server.py --http     # 127.0.0.1:8765, multi-client
```

The HTTP mode prints a token. Point the client at `http://127.0.0.1:8765/mcp`
and send it as the header `X-Jarvis-Token`.

---

## Two choices made against the obvious approach

### 1. Hand-written tools, not auto-converted routes

FastMCP will turn all ~123 FastAPI routes into tools in one line. FastMCP's own
documentation warns against shipping that: models perform markedly better
against a small curated surface than a mirrored API.

So there are fifteen tools, each named for an **intention** —
`search_the_web`, not `post_agents_desktop` — and each wrapping however many
internal calls it takes.

### 2. No low-level primitives

There is no `click_mouse`, no `press_key`.

If those were exposed, every client would build its own fragile ad-hoc
automation on top of them, and swapping Playwright or the OCR engine later would
break all of it. High-level tools keep the internals free to change.

---

## The tools

**Knowing**
`whats_on_this_machine` · `what_do_you_know_about_me` · `remember_about_me`

**Doing**
`preview_task` (steps only) · `simulate` (steps + effects, runs nothing) ·
`run_task` · `control_desktop` · `search_the_web` · `look_at_the_screen`

**Earning**
`find_freelance_jobs` · `review_proposals` · `earnings_report`

**Watching**
`current_plan` · `why_did_that_happen` · `stop_what_youre_doing` ·
`teach_by_watching`

`preview_task` and `simulate` exist so a client can check before it commits —
the same "show me first" the Planner screen offers.

---

## Security

This is the lethal trifecta in one process: private data (a browser logged into
the user's freelance accounts), untrusted content (every job description it
scrapes), and outbound communication.

- **Loopback only, always.** Never bind this to `0.0.0.0`. Enforced by
  `.semgrep/jarvis.yml` (`jarvis-listens-on-all-interfaces`).
- **Token required in HTTP mode.** Without it, anything else running on the same
  PC could drive the desktop.
- **Anything that submits, types or runs a command is not auto-approved.** It
  goes through the same approval queue the UI uses. An MCP client is not more
  trusted than the console.
- **Scraped text reaching a model is data, never instruction.**

## Adding a tool

1. Does an existing tool already cover it? Fifteen intentions beat forty verbs.
2. Name it for what the user wants, not for the endpoint it calls.
3. Never expose a primitive. If a client needs three tools in sequence to do one
   thing, that sequence belongs inside one tool.
4. If it types, submits, or runs a command, route it through the approval queue.

## Not installed?

`pip install fastmcp`. The module exits with that message rather than a
traceback — a missing optional dependency is a skip with an install hint, not a
failure.
