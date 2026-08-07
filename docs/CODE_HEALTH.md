# Code health

What the tooling found, what was fixed, and what was deliberately left alone.

Regenerate the evidence for any claim here with:

```
ruff check .
```
```
cd frontend && npx biome check src
```
```
semgrep scan --config .semgrep
```
```
python -m pytest backend/tests
```
```
python tools/failure_injection.py
```

Last full pass: 2026-08-04. Ruff clean, Biome 0 errors / 123 warnings,
Semgrep 0 findings, pytest 57 passed, failure injection 24 passed / 0 failed /
1 skipped — **and the same again with the optional display libraries stubbed to
fail**, which is the condition CI runs under and the one that found the bug
below.

---

## About the Semgrep rules

`.semgrep/jarvis.yml` holds ten **local** rules. The registry rulesets
(`p/python`, `p/security-audit`, …) are downloaded from semgrep.dev at scan
time and are not used, for two reasons:

1. The machine Jarvis runs on is in mainland China with no VPN. A lint step
   that has to reach a US host will not run where it matters.
2. Generic rules find generic bugs. These find *"someone re-introduced the
   thing we already fixed"* — which is the failure mode this project actually
   has.

Every rule was verified to fire against a deliberately-bad fixture before being
committed, and verified NOT to fire against the clean equivalent. One of them
(`jarvis-ollama-outside-providers`) silently matched nothing on the first
attempt: `from ollama import ...` with an ellipsis parses but matches nothing,
and takes the whole `pattern-either` down with it. A rule that reports zero
findings looks exactly like a rule that passed.

---

## Fixed

| Where | What | Why it mattered |
|---|---|---|
| `services/brain_service.py` | `zip(rows, embs)` → `strict=True` | A short embedding list left later chunks un-embedded and the backfill still reported success. Silent partial success. |
| `routes/automation.py:126` | bare `except: pass` → `except (ValueError, TypeError)` | Swallowed `KeyboardInterrupt` and `SystemExit` as well as the parse error. |
| `main.py` `/chat` | dropped a dead `_get_history()` call | One wasted DB query per chat message. (`/chat/stream` genuinely uses its copy — only this one was dead.) |
| `services/planner_service.py:131` | lambda closing over a loop variable → plain lookup | Harmless as written; one refactor from a real late-binding bug. |
| `agents/vision_agent.py:303` | `md5(..., usedforsecurity=False)` | It's a screenshot cache key, not a signature. Says so, so the security rule stays on honestly. |
| `services/deepseek_service.py:32` | removed dead `import ollama` / `from anthropic import Anthropic` | `call_model()` has delegated to `ai_router.ask()` for a while; these leftovers made the file still look like a provider. Ruff couldn't see them (bound in `try/except`), so they survived every previous cleanup. Semgrep found them. |
| `main.py` `/health` | probes via `ollama_manager.health()` | Was reaching for the SDK directly, bypassing the one door. |
| `agents/desktop_agent.py` | `known` variable removed | Computed, never read. |
| repo-wide | 107 mechanical Ruff fixes + import sort | Unused imports, empty f-strings, deprecated typing imports, trailing whitespace. |
| `frontend/src/pages/Agents.jsx` | unused `edge` import | |
| `frontend/src/pages/Logs.jsx` | dead `label` style object | |
| `frontend/src/JarvisOS.jsx` | `(grouped[k] ||= []).push(v)` → three plain lines | Correct, but dense enough to stop and parse. |

---

## Known gaps — real, and deliberately NOT fixed here

These change runtime behaviour. They belong in their own change, with their own
verification, not buried in a tooling commit.

### 1. The wall-clock cap on Ollama calls is computed and never applied
`backend/providers/ollama_provider.py:102`

`LIMITS` carries three bounds: max tokens, max context, and a **timeout**. The
first two are passed to `client.chat()`. The third is unpacked into `_` and
dropped.

It cannot currently be applied: `_client()` returns the ollama **module**, and
the module-level `chat()` takes no timeout. Enforcing one needs
`ollama.Client(timeout=...)`.

The comment directly above that code says unbounded generation *"has already
cost this project a 288-second screen analysis"*. So: a model that **rambles**
is bounded, and a model that **stalls** is not. On a 16 GB machine under memory
pressure, stalling is the more likely of the two.

**Fix:** build a `Client` with the timeout and use it. Needs a live Ollama to
verify, so it must be tested on the Windows machine, not here.

### 2. `/health` can report a model the system is not using
`backend/main.py:324`

`"model"` comes from `OLLAMA_MODEL`, a module-level env constant read at import.
The model actually in use is chosen at call time by `model_router`, based on RAM
free at that instant. These disagree the moment the router falls back.

This is the same bug already fixed once in Diagnostics and `os_state` — both now
ask `model_router`. `/health` was missed.

### 3. `/health` has no timeout, and the launcher believes it
`backend/main.py:324`

`START.bat` polls `/health` to decide whether the backend is up. The Ollama
probe inside it has no timeout. A slow or paging Ollama makes `/health` slow,
which makes the launcher call a working backend **offline** — a false report the
user has already hit once.

**Fix:** bound the probe, and report `ollama: "checking"` rather than blocking.

### 4. `deepseek_service.job_type` is parsed and thrown away
`backend/services/deepseek_service.py:~168`

The model is asked to classify the job type, the answer is parsed out of its
JSON, and nothing downstream ever receives it. Paid for on every call. Either
return it or stop asking for it.

### 5. React list keys use array indices — 24 sites
The live log feed, the trace list and the plan steps all key by index. When
items are prepended (which is exactly what a live feed does), React reuses the
wrong DOM nodes: expanded rows collapse, and the wrong row appears to update.

**Fix:** key by a stable id. Some of these lists already carry one.

### 6. `useExhaustiveDependencies` — 12 sites
Some are deliberate (the Earn page's poll interval intentionally depends only on
`submitting`). Others are probably stale closures. Each needs a judgement, which
is why Biome's blanket `--unsafe` fix is not the answer — see below.

### 7. `useButtonType` — 83 sites
`<button>` defaults to `type="submit"` **inside a form**. This app has no
`<form>` element, so all 83 are latent, not live. Demoted to a warning so new
buttons are still flagged.

### 8. Two `<div>`s carry `onClick`
`JarvisOS.jsx` trace rows and Planner step rows. Fixing properly means making
them `<button>`s, which changes layout and styling.

---

## What CI caught that local testing could not

The first CI run failed three jobs while everything passed locally. Worth
recording, because it is the clearest argument for having CI at all.

**`import pyautogui` does not raise `ImportError` on a headless machine.** It
pulls in mouseinfo, which runs `Display(os.environ['DISPLAY'])` at module scope
and raises `KeyError: 'DISPLAY'`. The guard was `except ImportError`, so
importing `desktop_agent` crashed rather than degrading to
`HAS_PYAUTOGUI = False` — taking down the import check and five
failure-injection scenarios with it.

It never reproduced locally because pyautogui simply isn't installed in the dev
container, so the ImportError path worked perfectly. **"Installed but unusable"
is a different state from "not installed", and only one of them was handled.**

The error message was wrong too: "Run: pip install pyautogui" for a package
that was already installed. Same class as telling the user to `ollama pull` a
model they already have — an error naming the wrong cause sends you hunting for
a bug that isn't there.

Fixed, with `backend/tests/test_headless.py` keeping both halves honest:
installed-but-unusable degrades and names the real cause; genuinely missing
still gets the install hint.

**`config.set()` silently did nothing on a database that had never been
initialised.** `services/config.py` assumed `models.db.init_db()` had already
run. Inside the running backend that holds — `main.py` calls it at startup —
but nothing else does: `tools/`, the failure-injection harness and
`mcp_server.py` all reach for config directly.

With no `settings` table, `set()` returned
`{"ok": False, "error": "no such table: settings"}`, and almost every caller
ignores that dict. **The value looked saved and wasn't.** That is the
"I set it, I saved it, nothing changed" bug config.py exists to prevent,
happening one layer below where it was being prevented.

It could not reproduce on any machine where Jarvis had been started once —
which is every dev machine. Config now creates its own table, retries the
write once, and still reports honestly if it genuinely can't (read-only disk,
locked database). `backend/tests/test_config_store.py` covers both halves, and
CI runs the harness on a fresh checkout.

**And `tools/check_ui.mjs` lied about why it failed.** It reported "vite never
came up. Run `npm install` in frontend/ first" on a runner where `npm ci` had
just succeeded. It swallowed both of vite's output streams and printed a guess.
The real cause: vite defaults to binding "localhost", which resolves to `::1`
first on the runner, so it listened on IPv6 while the probe polled 127.0.0.1.
Now it binds 127.0.0.1 explicitly and prints whatever vite actually said.

---

## A near-miss worth remembering

Running `biome check --write --unsafe` to clear the 83 `useButtonType` findings
also applied Biome's `useExhaustiveDependencies` fix, which appended
`loadPlans`, `loadMemory` and `loadDesktop` to a `useEffect` dependency array in
`Agents.jsx` **at line 111** — while those `const`s are declared at 118–129.

A dependency array is evaluated during render. All three would be read inside
their temporal dead zone: `ReferenceError`, component never mounts, blank page.

That is the same failure that took a day to find last month.

Biome flagged its own output (`noInvalidUseBeforeDeclaration`, 4 errors) and the
change was reverted. **`--unsafe` is not used anywhere, including CI.**

The lesson is not "Biome is bad". It is that an automated fix for a *style*
finding can introduce a *correctness* bug, and the only reason this was caught
is that the tool was run again afterwards and its output was read.
