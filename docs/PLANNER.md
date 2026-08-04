# Planner

How a sentence becomes steps.

`services/decompose.py` · `services/tool_registry.py` ·
`services/planner_service.py` · `services/live_plan.py` · `services/simulate.py`

---

## Deterministic before generative

Asked to "open qq and check messages", the old planner handed the goal straight
to the LLM. The model had never heard of QQ and produced:

> *"Visit a popular messaging platform like Telegram or WhatsApp. Enter 'qq' in
> the search bar…"*

Nonsense — because the system reached for the LLM before checking whether a
concrete tool already existed. That is the whole reason for the order below.

```
  sentence
     │
     ▼
  tool_registry.resolve_steps()      known command → exact steps, no LLM
     │  miss
     ▼
  decompose.decompose()              split into clauses, parse each one
     │  miss
     ▼
  planner_service.decompose()        the LLM, with hard rules in the prompt
```

Anything the first two can answer never reaches a model. A model is fast enough
to be wrong quickly and confident enough to be believed.

---

## Splitting a sentence

`decompose.split_clauses()` breaks at real step boundaries, and only there.

**A connector splits only when an action verb follows it.** That is what keeps
"black **and** decker" and "salt **and** pepper" whole while still separating
"search X **and** analyze the page". Connectors include `,` and `;` — people
write "open notepad, tell me a joke" constantly, and without the comma the
whole tail became the app name.

**Quoted spans are protected first.** `type "open the door and run"` is one
literal string, not three clauses. Splitting inside a quotation silently
corrupts text the user asked to be reproduced exactly.

**Juxtaposition is handled.** "open browser search bmw m4" has no connector at
all. `_split_juxtaposed()` handles it, but only after a launch verb and only
when the words before the second verb name an app we recognise — so "open read
me and weep.txt" is left alone.

**Nothing is silently dropped.** If a clause can't be parsed it goes into
`unresolved`, and the reply says what was skipped. Silent partial execution —
two clauses run, one didn't, and the answer says "Done ✓" — is the worst class
of bug in this project.

---

## Type vs write vs ask

Getting this wrong is bad in both directions, so the rule is conservative.

| You say | It does | Why |
|---|---|---|
| `type hello` | types `hello` | Literal is literal, always |
| `write hello` | types `hello` | Short phrase, no composition hint |
| `write about yourself` | **composes**, then types | "about " is a composition hint |
| `write a short intro for my site` | **composes** | ≥5 words after `write` reads as a brief |
| `type exactly hello world` | types it | "exactly" defeats composition, always |
| `open doubao and ask it how it is` | types the question, presses Enter | Doubao can answer |
| `open notepad tell me about yourself` | **composes**, no Enter | Notepad cannot answer anything |

That last row is a real bug that shipped: Notepad received the characters `me
about yourself`. The pronoun was left in the text, and a question aimed at a
text editor was treated as literal input. Asking an editor a question can only
mean "you answer it, and write the answer here".

`tool_registry._CONVERSATIONAL_APPS` is the list of things that can answer.

**Composed prose is never followed by Enter.** The composition *is* the answer;
an Enter after it adds a blank line to a document, or sends Jarvis's own essay
to a contact.

---

## Executing

`desktop_agent.execute_chain()` — see [DESKTOP_AGENT](DESKTOP_AGENT.md).

## Watching it happen

`services/live_plan.py` publishes the plan **before** it runs, so the Planner
screen shows what's about to happen rather than what already did.

`begin` / `ensure` / `step_start` / `step_end` / `skip` / `retry` / `finish`.

- **Skip** a step — recorded as skipped, not failed. The plan says *who* decided.
- **Retry** a failed step without re-running the whole chain.
- **Stop** — lands between steps, never inside one.

`ensure()` defers to a caller that already published a better-worded plan, so
the chat wording wins over the executor's.

## Trying it first

`services/simulate.py` — `task()` and `earning()` return what *would* happen:
the steps, what each one touches, how long it would take on this machine, and
what would stop it.

**It executes nothing.** That is asserted by a test
(`test_simulating_a_task_executes_nothing`) and by a failure-injection
scenario, because a preview that occasionally does the thing is worse than no
preview — it runs against a live desktop and a logged-in browser.

## Explaining a failure

`control.explain()` and `services/narrate.py` build the answer from the
execution trace and the live goal — **not** by asking a model to narrate its
own behaviour. A model asked to explain itself produces a plausible story
whether or not it matches what the code did, and being convincingly wrong is
worse than saying nothing.

## Projects

`services/planner_service.py` tracks multi-step goals across days: `todo`,
`doing`, `done`, `blocked`. Projects share a name with the Brain's `project`
tag, so facts saved "for mistore" line up with the mistore plan — one workspace
across knowledge and execution.

Its `decompose()` falls back to a keyword template when no LLM is available, so
the feature still produces a usable checklist offline.
