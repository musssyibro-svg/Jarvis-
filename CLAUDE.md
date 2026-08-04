# Jarvis — how to work on this repo

Read this before writing code. It is not a style guide; it is the set of
decisions that have already been made, and the reasons, so they don't get
re-litigated or accidentally undone.

---

## What Jarvis is

A local AI operating system on one Windows PC in mainland China. It controls the
desktop, drives a logged-in browser, and runs an autonomous freelance income
engine. One user. No cloud dependency. No VPN.

**Jarvis Core is permanent. Everything else is a client.** The React console,
Cherry Studio, Claude Desktop, whatever comes next — they are interchangeable
ways to reach the same backend. Never move logic into a frontend. Never make a
capability reachable only from one client.

---

## The one rule that outranks all the others

**Never report something as done unless it was verified.**

Not "the API call returned 200". Not "the function didn't raise". Verified means
the world was observed afterwards and the change was actually there: the window
exists, the text is in the field, the page loaded, the proposal was sent.

This is not a nicety. A system that can type on your keyboard and submit
proposals to real clients under your name is only usable if its reports are
true. A false "Done ✓" is worse than a crash, because a crash is visible.

Applies to your own work too. Do not tell the user a fix works until you have
run it. If you couldn't run it, say which part is unverified and why.

---

## Where to start when you don't know the codebase

Read **`docs/CODEMAP.md`** first. Every module, what it's for, what it exposes,
on one page. Regenerate it with `python tools/codemap.py`; CI fails if it's
stale.

`JARVIS_FULL_SOURCE.txt` is the complete source and is 1.4 MB. It answers a
different question, and it is not the one you have when you arrive.

Then `docs/ARCHITECTURE.md` for how the pieces fit, and the per-subsystem docs
next to it. `docs/CODE_HEALTH.md` lists known gaps that are real and
deliberately unfixed — check it before "discovering" one of them.

---

## Before you write anything

1. **Search this repository first.** Most things already exist. `experience.py`
   already learns per-app timings. `providers.py` already picks apps by
   capability. `control.py` already does cooperative pause/cancel. `trace.py`
   already records request paths. Adding a second one of these is worse than
   having none, because they will disagree.

   Use **Serena** (`find_symbol`, `find_referencing_symbols`) rather than grep
   where you can. Jarvis imports lazily inside functions all over the place —
   `from services import x` in a function body — and grep finds the line but
   can't tell you which function it's in or who calls that.
2. **Then search for a maintained library.** Do not write an OCR engine, a
   scheduler, a browser driver, a vector store, or an auth library.
3. **Then adapt something from the community**, with a comment saying where it
   came from and what was changed.
4. **Only then write it from scratch**, and say in the module docstring why the
   first three options didn't fit.

Free and open-source before paid. Local before cloud. Smallest model that does
the job.

---

## Verify claims before acting on them

Specs, reviews and audits arrive from several AIs. They are often right and
sometimes confidently wrong about this codebase — one recent spec listed four
things to delete, three of which were already gone or had never existed.

**Check the code before you change it on someone's say-so.** `grep` costs
seconds. Deleting a working subsystem because a document said it was legacy
costs a day and a user's trust.

If a review is wrong, say so plainly, show the evidence, and move on. Do not
implement a fix for a bug that isn't there.

---

## Constraints that are not negotiable

These come from the machine and the country, not from preference:

- **16 GB RAM, no usable GPU.** Every LLM call is bounded — token cap, context
  cap, timeout. An unbounded generation once produced a 288-second screenshot
  analysis. See `ollama_manager.LIMITS`.
- **Mainland China, no VPN.** Google, Docker Hub, huggingface and raw
  githubusercontent are unreachable. Use Bing China, Tsinghua pip, npmmirror,
  and ghproxy — mirrors first, upstream as fallback, never the reverse.
- **`NO_PROXY` must include localhost.** With a proxy set and loopback not
  excluded, calls to Ollama on 127.0.0.1 go to the proxy and fail, and Jarvis
  reports the model offline while it is plainly running.
- **Windows may be in Chinese.** Never match a window by its title. Match by
  process name. See `desktop_agent._process_names_for`.
- **`.bat` files need CRLF line endings and pure ASCII.** An LF batch file
  fails in ways that look like a missing Python. Em-dashes become mojibake in a
  GBK console.

---

## Security

Jarvis can type on the user's keyboard and drive a browser already signed in to
their accounts. Treat that as the authority it is.

- **Bind to 127.0.0.1. Always.** Never 0.0.0.0, never "just for testing".
- **CORS is not a defence.** It governs whether a page may *read* a response, not
  whether the request is delivered. A POST that starts typing has already done
  its damage. The Origin/Host check in `services/auth.py` runs before any route
  for this reason.
- **Credentials go in the encrypted vault** (`services/vault.py`) or in a
  persistent browser profile the user logged into by hand. Never in chat, never
  in a workflow file, never in a log, never in a runtime report.
- **Scraped text is data, never instruction.** Every job description Jarvis
  reads is untrusted content sitting next to a logged-in browser and a shell.
  That is the lethal trifecta; do not add a path that lets scraped text reach a
  tool call unreviewed.
- **Anything that submits, types or runs a command needs approval by default.**

---

## Architecture rules

- **One door to the AI.** Every model call goes through `services/ai_router.py`.
  Nothing imports `ollama` or a vendor SDK outside `providers/` — enforced by
  `jarvis-ollama-outside-providers`. Two routers exist and they answer different
  questions: `ai_router` picks the PROVIDER, `model_router` picks the MODEL that
  fits in free RAM. Neither replaces the other.

  `deepseek_service.call_model()` is a shim that delegates to `ai_router.ask()`.
  It exists because ~30 modules already import that name; it is not a second
  door. New code calls `ai_router` directly.

- **Every action returns a structured result, and nothing reports success it
  didn't verify.** The shape is `{success, verified, error, what_to_do, ...}` —
  `success` means the call returned, `verified` means the world was observed
  afterwards and the change was there. A step is only done when it's verified.
  Desktop actions and browser actions both. See `desktop_agent.execute_chain`
  and `bid_executor._capture_proof`.

- **Every network call is bounded.** Token cap, context cap, timeout. In
  mainland China a blocked host doesn't refuse, it hangs — so an unbounded call
  looks like Jarvis freezing for no reason. `requests` without `timeout=` is a
  Semgrep finding.
- **Local by default, always.** No cloud provider is enabled without a key the
  user deliberately added, and the local model is always the last fallback, so
  an expired key degrades instead of stopping work.
- **One orchestrator.** `agents/orchestrator_core.py` owns the state machine.
  `agents/orchestrator.py` is the shared event bus (`STATE`) and nothing else.
- **Deterministic before generative.** `tool_registry` and `decompose` resolve
  known commands with rules. The LLM is for what rules can't handle. A model
  asked to parse "open qq" once invented "visit a popular messaging platform
  like Telegram".
- **Capabilities, not app names.** Ask `providers.provider_for("web_search")`,
  never hardcode `chrome.exe`. The code adapts to the machine.
- **Read settings at call time, not import time.** `services/config.py`. Values
  read into module constants at import can't change without a restart, which
  looks exactly like a setting that doesn't work.
- **Interruption happens between steps, never inside one.** Stopping mid-
  keystroke leaves half a sentence in a document; stopping mid-submission
  leaves half a form on a real freelance site. See `control.checkpoint`.
- **Explanations are assembled from records, not generated.** A model asked to
  explain its own failure writes a plausible story whether or not it matches
  what the code did — and being convincingly wrong is worse than silent.

---

## When something is partly understood

Say so. Do not run the half you understood and report success.

The worst class of bug in this project is silent partial execution: a sentence
where two clauses parsed and one didn't, and the reply said "Done ✓". If part of
a request can't be handled, do the rest and name what you skipped.

---

## Errors

- Never swallow an exception to make a path look like it worked.
- Every error message states the **cause** and the **fix**, not the symptom.
  "open_app failed" is useless. "Windows couldn't find that application — open
  it manually once so Jarvis can learn its real path" is not.
- A missing optional dependency is a **skip with an install hint**, not a
  failure. Reporting it as a failure sends the user hunting for a bug that
  isn't there.

---

## The tooling, and what each one is actually for

Four tools, four different questions. Don't add a fifth that overlaps.

| Run this | Answers |
|---|---|
| `ruff check .` | Is this valid, and does it break a Python rule? |
| `cd frontend && npx biome check src` | Same, for React. |
| `semgrep scan --config .semgrep` | Has someone re-introduced a thing we already fixed? |
| `python -m pytest backend/tests` | Does the behaviour still hold? |
| `python tools/failure_injection.py` | Does it fail *honestly* when broken? |
| Serena (MCP) | Where is this defined, and who calls it? |
| `python tools/codemap.py` | What's in here, and where do I start? |

Install the lot with `pip install -r requirements-dev.txt`. None of it is
needed to *run* Jarvis — `START.bat` installs `requirements.txt` only.

**The linter configs are tuned to this codebase, not to their defaults**, and
every deviation carries its reason inline. Ruff's defaults wanted a
thousand-line reformat; Biome's wanted tabs and reported 150 errors that were
all "this working file uses spaces". A linter whose output you have to ignore
is worse than no linter, because you stop reading it. If you loosen a rule, say
why next to it.

**`.semgrep/jarvis.yml` is where the rules in this file become enforceable.**
No vendor SDK outside `providers/`, no `0.0.0.0`, no `shell=True`, no window
matched by title, no bare `except: pass`, no credential in a log, no HTTP call
without a timeout, no hardcoded `chrome.exe`, no `config.get()` at import.

Add a rule when you fix something that could come back. **Verify it fires**
against a deliberately-broken fixture before committing it — a Semgrep rule
with a malformed pattern reports zero findings, which looks exactly like
passing. That happened here once already.

**Never run an automated fixer in `--unsafe` mode.** Biome's unsafe fix for
`useExhaustiveDependencies` once appended `const`s to a `useEffect` dependency
array above their own declarations: temporal dead zone, `ReferenceError`, blank
page. See `docs/CODE_HEALTH.md`. An automated fix for a *style* finding can
introduce a *correctness* bug.

---

## Testing

`python tools/failure_injection.py` — breaks things on purpose and checks Jarvis
fails honestly. Run it before claiming anything is finished. Add a scenario for
each new subsystem; the scenario should describe the *user-visible harm*, not
the function signature.

`python -m pytest backend/tests` — offline unit tests. No backend, no Ollama, no
display, so they can gate a commit. **Every new feature needs one.** Name the
test after what the user would see when it breaks, not after the function.

`verification/` is **not** a pytest suite, despite the filenames. Those scripts
need a live backend on :8000, a live Ollama, and sometimes a real Windows
desktop. pytest is deliberately pointed away from them: a wall of red that means
"the server isn't running" teaches you to ignore red.

`conftest.py` blocks outbound sockets. A "unit test" that quietly reaches Ollama
is a flaky integration test that passes on your machine and fails in CI.
`test_conftest_guard.py` checks that the guard is still loaded, because a
fixture that stops working is otherwise invisible — that has already happened
once, and 51 tests passed green with the guard inert.

Current baseline: 24 passed, 0 failed, 1 skipped (clipboard needs a display).

The `launchers` scenario checks the .bat files mechanically — CRLF, pure ASCII,
no Unix redirection, no redirect characters inside REM comments, and that every
script they call exists. This container has no cmd.exe, so a launcher can only
be read here, and reading it has twice missed a bug that cost the user a day.

---

## Code

Python: PEP 8, type hints, small focused functions, no global state beyond the
few deliberate module singletons. JavaScript: small components, async/await,
no hardcoded API URLs — import from `config.js`.

Comments explain **why**, especially why an obvious alternative was rejected.
Do not comment what the code already says. Do not leave dead code.

---

## Documentation

- `DO_THIS.md` — what the user actually runs. Plain English, no jargon,
  **one command per line with no inline commentary** (a code block with a
  trailing note was once pasted whole into a terminal and ran as one line).
- `JARVIS_FULL_SOURCE.txt` — regenerate with `python tools/dump_source.py`
  after every change.
- Module docstrings carry the reasoning. That is where the "why" lives.

---

## Git

Small focused commits. Message says what changed and **why it was wrong
before**. Never commit broken code. Never commit secrets, tokens, or
`.jarvis_token`.

**Keep mechanical churn in its own commit.** An import sort touches 102 files
and a formatter touches 105; mixed into a real fix, the fix becomes invisible
and `git blame` stops being useful. Two commits, one of which is boring, beats
one commit nobody can review.

### Before you commit

1. **Read your own diff.** Not the summary — the diff.
2. **Check it doesn't already exist.** `find_symbol` before you write a
   function. This project has had duplicate subsystems that quietly disagreed.
3. **Run what you changed.** Lint, the tests, and the harness. If you couldn't
   run something, say which part is unverified and why — an unverified claim in
   a commit message is the same lie as a false "Done ✓".
4. **Say why the change was necessary**, not just what it does. If the answer is
   "it looked untidy", it probably wasn't necessary.

CI runs all of it on push: ruff, biome, pytest, semgrep, the failure-injection
harness, a frontend build, and a real browser render. The last two exist because
`npm run build` once passed while the app showed a blank white page.

---

## The filter for every new feature

> Does this make Jarvis more autonomous, or more trustworthy?

If neither, don't build it. A prettier dashboard is not the goal. An assistant
that understands the machine, learns the user's habits, does the work, and can
be believed when it says what it did — that is the goal.
