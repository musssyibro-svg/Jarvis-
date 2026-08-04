# Architecture

What Jarvis is made of and why the pieces are arranged this way.

Start with **[CODEMAP.md](CODEMAP.md)** if you want the file-by-file index. This
document is the shape, not the contents.

Per-subsystem detail:
[AI_ROUTER](AI_ROUTER.md) ·
[PLANNER](PLANNER.md) ·
[DESKTOP_AGENT](DESKTOP_AGENT.md) ·
[BROWSER_AGENT](BROWSER_AGENT.md) ·
[MEMORY](MEMORY.md) ·
[FREELANCER](FREELANCER.md) ·
[MCP](MCP.md)

---

## The one-sentence version

A FastAPI backend on `127.0.0.1` that can drive the Windows desktop, drive a
logged-in browser, and run a freelance income engine — with a React console
that is one client among several.

## The shape

```
    Chat / Console (React)      Cherry Studio, Claude Desktop, …
              │                              │
              │  HTTP + SSE                  │  MCP (stdio or 127.0.0.1:8765)
              ▼                              ▼
    ┌───────────────────────────────────────────────────┐
    │  auth gate  — raw ASGI, runs BEFORE any route     │
    └───────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────┐        ┌──────────────────────┐
    │ commander       │        │ orchestrator_core    │
    │ _adapter        │        │ state machine        │
    │ (one command)   │        │ (a long-running goal)│
    └────────┬────────┘        └──────────┬───────────┘
             │                            │
             ▼                            ▼
    ┌───────────────────────────────────────────────────┐
    │  decompose → tool_registry → execute_chain        │
    │  act → observe → verify → retry → record          │
    └────────┬──────────────────────────┬───────────────┘
             ▼                          ▼
      desktop_agent               browser_agent
      (pyautogui, win32)          (Playwright, persistent profile)
             │                          │
             └──────────┬───────────────┘
                        ▼
             ┌──────────────────────┐
             │ ai_router → provider │   ollama (local, always last)
             │ model_router → model │   deepseek / glm / kimi / …
             └──────────────────────┘
                        │
                        ▼
                  SQLite (WAL)
```

---

## The decisions, and what happens if you undo them

### Jarvis Core is permanent. Every UI is a client.

The React console, Cherry Studio, Claude Desktop, whatever comes next — all
reach the same backend. No capability is reachable from only one client, and no
logic lives in a frontend.

*Undo it and* a feature exists only where you happened to build it, and the
next client has to reimplement it.

### One door to the AI

Every model call goes through `services/ai_router.py`. No vendor SDK is
imported outside `backend/providers/`.

Before this, `call_model` was imported in ~30 files and `ollama.chat()` was
called directly in two more — one of which bypassed every cap and fallback the
rest of the system had. Changing provider meant editing thirty files and hoping
none were missed.

Enforced by `.semgrep/jarvis.yml`. See [AI_ROUTER](AI_ROUTER.md).

### Two routers, different questions

`ai_router` picks the **provider**. `model_router` picks the **model that fits
in free RAM**. Neither replaces the other — `model_router` holds the
machine-specific knowledge that makes a 16 GB machine usable, and `ai_router`
never looks at a model name.

### One orchestrator

`agents/orchestrator_core.py` owns the state machine and an explicit transition
table. `agents/orchestrator.py` is the shared event bus (`STATE`) and nothing
else.

`IDLE → PLANNING → SCOUTING → PROPOSING → EXECUTING → VERIFYING → COMPLETE`,
with `RECOVERING`, `FAILED`, and `STOPPED`. `STOPPED` is separate from `FAILED`
on purpose: a user pressing Stop is not an error, and filing it as one made the
console cry wolf and poisoned the reliability figures `experience.py` learns
from.

### Deterministic before generative

`tool_registry` and `decompose` resolve known commands with rules. The LLM is
for what rules can't handle.

A model asked to parse "open qq" once invented *"visit a popular messaging
platform like Telegram"*. See [PLANNER](PLANNER.md).

### Nothing is done until it's verified

Every action returns `{success, verified, error, what_to_do}`. `success` means
the call returned. `verified` means the world was observed afterwards and the
change was actually there.

This is the rule the whole project rests on: a system that can type on your
keyboard and submit proposals under your name is only usable if its reports are
true. A false "Done ✓" is worse than a crash, because a crash is visible.

### Interruption lands between steps, never inside one

`services/control.py`. Long loops call `checkpoint()` between steps; that's
where a pause or cancel takes effect.

Stopping mid-keystroke leaves half a sentence in a document. Stopping
mid-submission leaves half a form on a live freelance site. The cost is that a
pause can take as long as the current step.

Cancel is global — one Stop button must halt whatever is running — which is why
`run_scope()` exists to tell a live cancel from a leftover one. One press of
Stop once killed every command for the rest of a session.

### Capabilities, not app names

Ask `providers.provider_for("web_search")`, never hardcode `chrome.exe`. The
code adapts to the machine; the machine does not have to match the code. This
user's PC has Edge and no Chrome.

### Settings are read at call time

`services/config.py`, backed by SQLite — the same store the Settings screen
writes. A value read into a module constant at import can't change without a
restart, which from the outside is indistinguishable from a setting that
doesn't work.

### Explanations are assembled from records, not generated

`services/narrate.py` and `control.explain()` build the answer to "why did that
fail?" from the execution trace. A model asked to explain its own failure
writes a plausible story whether or not it matches what the code did — and
being convincingly wrong is worse than being silent.

### Three questions, three records, one module

`services/trace.py` answers all three, and they are genuinely different:

| Question | What answers it | Where to see it |
|---|---|---|
| What happened? | trace steps, per request | `/os/traces`, Logs → Request traces |
| What did it cost? | the rolling cost table | `/os/profile`, Logs → Speed |
| What actually broke? | failure records, with traceback | `/os/failures`, Logs → Failures |

The cost table is deliberately separate from the trace ring buffer: most slow
work happens with no trace open, on the income engine's and the watchdog's
background threads. Measuring only what the chat box triggers would profile the
fast half of the system.

The profile ranks by TOTAL time, not by the worst single call. 400 ms on every
action costs more than 30 seconds once an hour, and ranking by max sends
whoever reads it off optimising the wrong thing.

Failure records carry the traceback, the timing, and the surrounding state,
with credentials stripped by `trace._safe_value` before anything is stored —
these are served over HTTP and land in the downloadable runtime report, which
is a file the user emails. Parameters named like secrets are redacted; typed
text is reduced to its length, because "type my password" puts a credential in
a field called `text` that no name-based rule would catch.

---

## Security posture

Jarvis can type on the user's keyboard and drive a browser already signed in to
their accounts. Treat that as the authority it is.

- **Binds `127.0.0.1`.** Never `0.0.0.0`, never "just for testing".
- **The gate runs before any route.** `services/auth.py`, as raw ASGI
  middleware. Not `BaseHTTPMiddleware` — that breaks SSE streaming, which the
  live feed depends on.
- **CORS is not a defence.** It governs whether a page may *read* a response,
  not whether the request is delivered. A POST that starts typing has already
  done its damage.
- **Origin and Host are both checked**, so a hostname that resolves to
  127.0.0.1 doesn't get in (DNS rebinding).
- **Control paths need the token** even on loopback: `/agents/desktop`,
  `/os/control`, `/os/teach`, `/automation/queue`, `/workflows/run`, and the
  rest of `auth.CONTROL_PREFIXES`. `DESKTOP_CONTROL_ENABLED=0` switches them
  all off.
- **Credentials live in the encrypted vault** (`services/vault.py`) or in a
  browser profile the user logged into by hand. They are masked out of
  `/settings/effective` before it reaches a runtime report, because those get
  emailed.
- **Scraped text is data, never instruction.** Every job description Jarvis
  reads is untrusted content sitting next to a logged-in browser and a shell.
  No path lets scraped text reach a tool call unreviewed.

---

## Constraints that shaped this

Not preferences — they come from the machine and the country.

**16 GB RAM, no usable GPU.** Every LLM call is bounded: token cap, context
cap, timeout. An unbounded generation once produced a 288-second screenshot
analysis. `ollama_manager.LIMITS`.

**Mainland China, no VPN.** Google, Docker Hub, huggingface and
raw.githubusercontent are unreachable. Mirrors first (Bing China, Tsinghua pip,
npmmirror, ghproxy), upstream as fallback, never the reverse. This is also why
the Semgrep rules are local rather than fetched from semgrep.dev.

**`NO_PROXY` must include localhost.** With a proxy set and loopback not
excluded, calls to Ollama on 127.0.0.1 go through the proxy and fail — and
Jarvis reports the model offline while it is plainly running.

**Windows may be in Chinese.** Never match a window by its title; Notepad is
记事本. Match by process name.

**`.bat` files need CRLF and pure ASCII.** An LF batch file fails in ways that
look like a missing Python. Em-dashes become mojibake in a GBK console.
