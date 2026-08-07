# The brain layer

> Renamed from a root-level `ARCHITECTURE.md`. Two files with that name saying
> different things is exactly the "two sources that disagree" problem this
> project keeps hitting — see [ARCHITECTURE.md](ARCHITECTURE.md) for the whole
> system. This document covers one layer of it: the Brain and what feeds it.

This is the layer the roadmap docs kept asking for. It sits *under* the existing
agents/pipeline — additive, nothing old was deleted (the legacy orchestrator
still powers part of freelance, per the "migrate, don't rip out" caution).

```
                          Brain  (services/brain_core.py)
                            │  owns + presents, one mind
   ┌───────────────┬────────┼─────────────┬──────────────┬───────────────┐
   │               │        │             │              │               │
World Model    Capability  Event Bus   Reflection      Memory /        Model
(world_model)  Registry    (event_bus) (reflection)    Brain KB        Router
 what's true   what I can   nervous     what I learned  what I know    which model
   now         do (data)    system                     (brain_service) (model_router)
```

## The pieces

- **Event Bus** (`services/event_bus.py`) — internal pub/sub. Modules publish
  (`app.opened`, `job.found`, `workflow.done`, `login.changed`, `system.ram_high`)
  and anyone subscribes. Makes Jarvis event-first instead of only chat-driven.
  Read via `GET /events/recent`.

- **World Model** (`services/world_model.py`) — the Brain's live picture of
  reality: open windows/apps, logged-in platforms, system load, income engine,
  active plans, current model. A background poller diffs snapshots and publishes
  change events → proactive reactions. `GET /world/snapshot`, `/world/summary`.

- **Capability Registry** (`services/capability_registry.py`) — every ability is
  a `Capability` (name, category, inputs, outputs, requirements, confidence,
  keywords). The planner asks `best_for(goal)` — "which capability solves this?"
  — with a live requirements check (is Playwright installed? a platform logged
  in?). Grows automatically from learned workflows + custom agents.
  `GET /brain/capabilities`, `POST /brain/route`.

- **Reflection Engine** (`services/reflection.py`) — after a workflow/plan runs,
  derive a concrete lesson from the real step outcomes (what retried, where it
  broke), store it in the personal brain, and flag failing workflows for repair.
  This is how Jarvis improves, not just repeats. `GET /brain/reflections`.

- **Model Router** (`services/model_router.py`) — route by task class
  (chat/proposal/reflection → fast, planning → reasoning, screen → vision) and
  unload heavy models from RAM after one-off use. `GET /router/status`.

- **Brain** (`services/brain_core.py`) — owns the World Model, subscribes to the
  bus, and runs the proactive loop ("should I act? involve the user only if
  needed" → nudges via Pulse, never irreversible actions on its own).
  `GET /brain/state` returns the unified snapshot.

## New chat verbs

- `what can you do` — lists capabilities from the registry.
- `status` / `what are you doing` — the World Model summary.
- `teach <name>: <steps>` then `run my <name>` — self-learning workflows.

## Still open (roadmap order for next passes)

Skill discovery (auto-detect installed apps/platforms as capabilities),
memory optimizer (archive + cap history for RAM), and a fuller model router
with per-task benchmarking. The scaffolding above is what those plug into.
