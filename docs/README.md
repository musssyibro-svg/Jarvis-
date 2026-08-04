# Jarvis docs

**New here? Read in this order:**

1. **[CODEMAP.md](CODEMAP.md)** — every module, what it's for, what it exposes.
   One page. Generated from the AST; regenerate with `python tools/codemap.py`.
2. **[ARCHITECTURE.md](ARCHITECTURE.md)** — the shape of the system, and why
   each decision is the way it is.
3. **[../CLAUDE.md](../CLAUDE.md)** — the rules. Read before writing code.

Do **not** start with `JARVIS_FULL_SOURCE.txt`. It is the complete source,
1.4 MB, regenerated on every change. It answers a different question.

---

## Subsystems

| Doc | Covers |
|---|---|
| [AI_ROUTER](AI_ROUTER.md) | One door for every model call; the two routers and why both exist |
| [PLANNER](PLANNER.md) | Sentence → steps. Deterministic before generative |
| [DESKTOP_AGENT](DESKTOP_AGENT.md) | Mouse, keyboard, windows — and the verification rules |
| [BROWSER_AGENT](BROWSER_AGENT.md) | Playwright, persistent logins, the browser lease |
| [MEMORY](MEMORY.md) | Four things called "memory", and which is which |
| [FREELANCER](FREELANCER.md) | The income engine, and receipts |
| [MCP](MCP.md) | Driving Jarvis from Claude Desktop / Cherry Studio |
| [BRAIN_LAYER](BRAIN_LAYER.md) | Event bus, world model, capability registry, reflection |

## Health

**[CODE_HEALTH.md](CODE_HEALTH.md)** — what the tooling found, what was fixed,
and the known gaps that are real and deliberately unfixed.

**Check it before "discovering" a bug.** Several are already known, with the
reason they weren't fixed in a tooling pass written down.

## For the user, not for developers

`../DO_THIS.md` — plain English, one command per line, no jargon. That is the
file the user actually runs from; keep it that way.

---

## Keeping these true

A stale doc is worse than none: it sends you to a module that moved.

- `CODEMAP.md` is regenerated and diffed by CI. It cannot go stale silently.
- The rest are prose and are **not** checked automatically. If you change how a
  subsystem works, change its doc in the same commit.
- Module docstrings carry the reasoning — that is where the "why" lives, per
  CLAUDE.md. These documents summarise and connect; they do not replace them.
  When the two disagree, the docstring is next to the code and is more likely
  right.
