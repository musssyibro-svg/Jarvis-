# Memory

Four different things are called "memory". They are not interchangeable.

| Layer | Module | Holds | Lifetime |
|---|---|---|---|
| **Persona** | `services/persona.py` | Durable facts about the user | Forever, until forgotten |
| **Brain** | `services/brain_service.py` | Retrievable knowledge (RAG) | Forever |
| **World model** | `services/world_model.py` | What is true *right now* | Seconds |
| **Experience** | `services/experience.py` | What this machine is like | Learned, refined |

Plus `services/reflection.py`, which writes a lesson after work finishes, and
`services/trace.py`, which records the path every request took.

---

## Persona — facts about the user

Injected into every plan via `prompt_block()`, so Jarvis stops asking things it
has already been told.

**Precedence is the whole design:**

```
STATED    (2)  — you said it. Beats everything, never overwritten.
INFERRED  (1)  — noticed from behaviour (you keep picking Edge)
OBSERVED  (0)  — read off the machine by environment.py (no Chrome installed)
```

A machine scan must never overwrite something the user explicitly said. If you
tell Jarvis you prefer Firefox and the scanner doesn't find it, the scanner does
not get to win — it records what it saw at a lower rank and the stated
preference stands.

`remember()` / `forget()` / `all_facts()` / `learn_from_text()`. Editable on the
Memory screen — everything Jarvis believes about you, in one place you can
correct.

---

## Brain — retrievable knowledge

SQLite in the existing `jarvis.db`. No new database, no server.

**Zero required downloads.** Retrieval falls back to BM25 keyword search — pure
Python, stdlib only — so the Brain works on day one on a fresh machine, offline,
behind any firewall. That matters here: this machine is in China with no VPN,
and "install a 2 GB embedding model first" is not a working default.

`ollama pull nomic-embed-text` (~274 MB, CPU-friendly) upgrades it to semantic
search. Chunks are embedded lazily; anything ingested while Ollama was down is
backfilled next time it's up.

Vectors are stored as `float32` blobs via `array('f')` — stdlib only, no numpy
needed at ingest or search time.

```
brain_documents(id, title, source, project, chars, created_at)
brain_chunks(id, doc_id, seq, text, embedding)
```

`source` distinguishes kinds without extra tables: `note` / `file` / `chat` for
general knowledge, `fact` for personal facts, `reflection` for lessons.

`project` shares its namespace with the Planner's projects, so facts saved "for
mistore" line up with the mistore plan — one workspace across knowledge and
execution.

The Memory screen's search box runs the **real** retrieval, so you can see what
a question would actually pull up rather than trusting that it works.

---

## World model — what's true now

`services/world_model.py`. Which apps are open, which platforms are logged in,
what the system is doing. Publishes change events on `services/event_bus.py`.

Short-lived by design. If you find yourself persisting it, you want the Brain.

---

## Experience — what this machine is like

`services/experience.py`. Per-app launch timings measured on **this** PC, not
guessed. Which apps habitually fail their first cold start. Which errors are
worth retrying.

`classify(error, action, result)` → `{kind, cause, remedy, retryable, recovery}`.
This is what turns "open_app failed" into a sentence naming the fix.

---

## Reflection — a lesson after the work

`services/reflection.py`, fed by `brain_decision.after_goal()` (orchestrator)
and `desktop_agent._learn_from_chain()` (chat).

**Rule-based first.** The lesson is derived from real step outcomes — how many
verified, which retried, where it broke — and only *then* summarised by the fast
model if one is available. No LLM still produces a useful lesson, never a
fabricated one.

Only failures and retried runs reflect. A clean run teaches nothing, and this
machine cannot spare a model call after every "open notepad".

Both call sites were missing for a long time, and a runtime report said
`reflections: 0` — a learning loop nobody feeds is indistinguishable from no
learning loop.

---

## What must never be remembered

- **Passwords.** `services/teach.py` drops keystrokes typed into a window whose
  title looks like a login — in English **and** Chinese (`登录`, `密码`). The
  workflow records a `credential` placeholder that reads from the vault at
  replay time. Tested in `backend/tests/test_security.py`.
- **API keys.** `config.is_secret()` masks them out of `/settings/effective`
  before it reaches a runtime report, because those get emailed.

## Storage

One SQLite file, WAL mode. `services/maintenance.py` checkpoints the WAL hourly
and vacuums weekly — on a schedule, not after every cleanup, because a VACUUM on
every operation is how a 24/7 process spends its day doing nothing useful.
