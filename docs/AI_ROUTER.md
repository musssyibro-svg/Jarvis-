# AI Router

`backend/services/ai_router.py` · `backend/services/model_router.py` ·
`backend/providers/`

Every model call in Jarvis goes through one function.

```python
from services.ai_router import ask
text = ask(task="planning", prompt="...")
```

---

## Two routers, and this is the thing people get wrong

| | Question | Answers with |
|---|---|---|
| `ai_router` | **Which provider?** | ollama, deepseek, glm, kimi, openrouter… |
| `model_router` | **Which model?** | the strongest one that fits in free RAM |

They are not duplicates and neither replaces the other.

`model_router` holds the machine-specific knowledge that makes Jarvis usable on
16 GB — it is why a 0.5B model correctly wins when memory is at 87%.
`ai_router` sits above it and never looks at a model name at all.

If you find yourself adding model-size logic to `ai_router`, or provider
selection to `model_router`, you're in the wrong file.

---

## Why one door

`call_model` was imported in about thirty files, and `ollama.chat()` was called
directly in two more. Changing the provider meant editing thirty files and
hoping you missed none. Worse: one of the direct calls, in `main.py`'s
streaming endpoint, bypassed **every** cap and fallback the rest of the system
had — it ignored the RAM-aware model choice and the token limits that stop a
small model rambling for minutes.

Now the provider is a setting, not a code edit.

`deepseek_service.call_model()` still exists and still works — it delegates to
`ai_router.ask()`. That was deliberate: rewriting thirty call sites at once
risks missing one, and a thirty-file diff is unreviewable. One change routed
every existing caller through the gate immediately. **New code calls
`ai_router` directly.**

---

## Configuration

From `services/config.py` — the SQLite settings table the UI already writes.
Not a YAML file: that would add a dependency and a second source of truth, and
two places to disagree is how this project has been bitten before.

| Setting | Meaning |
|---|---|
| `ai_route_<task>` | Provider for this task (blank → `ai_route_default`) |
| `ai_route_default` | Fallback for everything (default `ollama`) |
| `ai_fallback` | Comma-separated chain to try when the first fails |
| `ai_<name>_api_key` | Key for a cloud provider. **Masked** out of every report |

**Local by default, always.** No cloud provider is enabled without a key the
user deliberately added, and `ollama` is always last in the chain — so an
expired key degrades instead of stopping work.

Read at call time, so changing a setting takes effect without a restart.

---

## Tasks

`ai_router.ask(task=...)` picks the route; `model_router` maps the task to a
quality floor and hardware needs.

| Task | Min quality | Heavy | Vision |
|---|---|---|---|
| `routing` | 2.0 | no | no |
| `chat` | 4.0 | no | no |
| `summary` | 4.0 | no | no |
| `reflection` | 4.5 | no | no |
| `proposal` | 5.0 | no | no |
| `planning` | 5.5 | yes | no |
| `reasoning` | 6.0 | yes | no |
| `vision` | — | yes | yes |

A task that needs more quality than the free RAM allows does **not** fail — it
falls back to the best model that fits, and the shortfall is reported rather
than hidden. That reporting is the point: "Jarvis feels dumb today" should have
a visible cause.

---

## Providers

`backend/providers/` is the **only** place a vendor SDK may be imported.
Enforced by `.semgrep/jarvis.yml` (`jarvis-ollama-outside-providers`).

- `base.py` — the interface. `configured()`, `chat()`, `stream()`.
- `ollama_provider.py` — local. Always available, always the last fallback.
- `openai_compatible.py` — one file for every OpenAI-shaped API. `PRESETS`
  carries the base URL and default model for deepseek, glm, kimi, openrouter,
  omniroute, openai, gemini and lmstudio. Adding a provider of this shape is a
  dict entry, not a new module.

## Bounds

Every call is capped: `num_predict`, `num_ctx`, and a wall-clock timeout, from
`ollama_manager.LIMITS`. Unbounded generation is not theoretical here — it
already cost a 288-second screenshot analysis.

**Known gap:** the wall-clock cap is computed and not applied, because
`_client()` returns the ollama module rather than a configured `Client`. Tokens
and context are bounded; time is not. See
[CODE_HEALTH](CODE_HEALTH.md#1-the-wall-clock-cap-on-ollama-calls-is-computed-and-never-applied).

## Failure

`ask()` never raises. Errors come back as readable `[...]` text, because
callers all over Jarvis put that string straight in front of the user. A
provider with no key reports itself unconfigured and is skipped silently — a
missing optional key is a skip, not a failure.

## Adding a provider

1. If it speaks the OpenAI protocol, add a `PRESETS` entry in
   `openai_compatible.py`. That's it.
2. Otherwise add a module in `providers/` implementing `base.Provider`.
3. Register it in `ai_router`'s provider table.
4. Never import its SDK anywhere else. Semgrep will tell you if you do.
