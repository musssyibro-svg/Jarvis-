# Jarvis V14 — Verification & Architecture Pass (QA report)

**Framing:** this was a stabilization/verification milestone, not a feature sprint.
I traced the real execution paths instead of assuming the previous edits worked.

**Hard limitation (stated up front):** I cannot launch Jarvis on Windows from this
environment — no display, no Ollama, no pyautogui/pygetwindow/Tesseract, not even
FastAPI installed. So I **cannot click through the running app**. What I *can* do,
and did: trace each request path statically from UI → route → handler, prove which
code actually runs, find legacy/silent fallbacks, fix them, and unit-test the pure
logic. Anything requiring a real screen/keyboard is marked **NEEDS LIVE RUN**.

Legend: ✅ verified in code + unit test · 🔧 fixed this pass · ⚠️ needs a live run to confirm · ❌ still broken

---

## 1. Architecture audit — what actually runs

| Path | Finding | Status |
|---|---|---|
| `/chat` → `handle_chat` | On ANY exception it silently fell back to plain `call_model` — hid feature failures, made everything "feel identical" | 🔧 now logs loudly, emits to feed, returns an explicit error (main.py `chat()`) |
| Vision intent (`"analyze my screen"`) | `perception.observe()` called the upgraded `analyze_screen` but read keys `text`/`analysis`/`ocr_text` that it never returns → always got `""` → looked broken | 🔧 reads real keys (`answer`/`ai_answer`/`screen_text`); vision intent now routes through the verified screenshot→analyze chain (commander_adapter, perception_agent) |
| Desktop command executor | Chat desktop commands go through **`execute_chain`** (the verified engine) via commander_adapter — NOT a duplicate executor | ✅ confirmed single path |
| Compound "open X then type" | Focus-gate only fired when input *immediately* followed `open_app`; with `wait_for_window` in between, nothing focused the window → typing missed (then honestly failed) | 🔧 focus now enforced before *any* input step regardless of ordering; unit-tested |
| Legacy `automation_engine.run_auto_mode` | Not called anywhere; `/automation/status` + `/stop` read/wrote its dead `_state` dict | 🔧 both routes now use the real orchestrator STATE + income engine |
| Legacy `orchestrator.run_pipeline` | Not called; only the SSE `STATE` object from that module is used (shared feed) | ✅ harmless; left in place |
| Two planner endpoints | `/planner/project` (planner_service, used by Core Plans) vs `/agents/planner/create` (OrchestratorCore, old Agents tab) — genuinely different | ⚠️ documented; Core Plans is the desktop-fixed one. Consolidation of the old Agents planner tab deferred to avoid churn |

---

## 2. Every reported complaint — traced

| Complaint | Root cause (traced) | Fix | Confirm |
|---|---|---|---|
| **QQ launch fails after first run** ("Windows can't reach the file qq") | `open_app` fell back to `cmd /c start qq`, which pops that dialog for a non-shell name | `app_resolver.py` finds the real .exe (Start Menu/registry/dirs), caches it, launches it directly; the `cmd /c start <bareword>` fallback is removed | ⚠️ NEEDS LIVE RUN (Windows-only APIs) |
| **Notepad opens but never types** | `type_text` was "trusted"; window wasn't focused before typing | focus enforced + confirmed before typing; if focus fails the chain STOPS honestly; typed text verified via clipboard round-trip | ✅ logic unit-tested · ⚠️ real keystrokes NEED LIVE RUN |
| **Doubao planner → phone/mobile steps** | planner LLM prompt wasn't desktop-scoped; doubao wasn't a known app | doubao/douyin/kimi added; decompose + step-classify prompts forbid phone/website/signup steps; app goals route through the registry; lenient JSON parse fixes the `Expecting ',' delimiter` crashes | ✅ registry path unit-tested · ⚠️ LLM output NEEDS LIVE RUN |
| **"open doubao and ask how it is" only opened** | compound "ask" clause was dropped | registry handles "open X and ask/type/say/search Y" → open, focus, type, Enter (Enter only for send/ask/search, not for Notepad) | ✅ unit-tested |
| **Screenshot analysis doesn't understand the screen** | (a) vision-intent path returned empty (key bug above); (b) screenshot captured the wrong/unfocused window; (c) no llava installed → OCR of whole screen incl. background | (a) fixed; (b) `open_app` now focuses the app so a following screenshot captures IT; (c) `analyze_screen` already prefers llava then OCR→LLM | ⚠️ true "understanding" NEEDS llava pulled + LIVE RUN |
| **False "Done"** | trusted verification + focus-gate hole | verified engine + focus-before-input + clipboard verify; `/chat` no longer masks errors as chat | ✅ logic verified · ⚠️ end-to-end NEEDS LIVE RUN |
| **CPU extremely high** | `/world/summary` re-enumerated all processes+windows on every poll; `/stats` did a 0.3s blocking CPU sample per poll; tight frontend polling | summary reads cached snapshot; poller 15→25s; `/stats` non-blocking; Core poll 5→8s, AutoMode 3→6s | ✅ code confirmed · ⚠️ note: peak CPU during Ollama inference is the model itself, not Jarvis |
| **Freelance approval clears the queue** | approving RemoteOK (a job *board*) correctly turns items to `ready` (apply externally) → looked like they vanished | queue shows ready/needs_login counts + a plain explanation; guidance to scan a real bid platform | ✅ confirmed (behavior was correct; UX was misleading) |
| **v3/v4/v5 version labels** | scattered hardcoded strings | single `JARVIS_VERSION="14.0"`; removed stray labels in main.py, UI.jsx, Workspace.jsx, AutoMode.jsx, Agents.jsx | ✅ grep-confirmed |

---

## 3. UI redesign (Core)

- Kept the fake neural-core/particles **removed** (as required).
- Redesigned the Core into coherent sections with **purposeful motion**: a state
  banner that only animates (`busy-sweep`, `think-ring`, `alive` glow) when Jarvis
  is genuinely thinking/executing/scouting/proposing — static when idle; a real
  System-status row with smooth progress bars; Ask/quick-actions; and a live
  **Activity Timeline** driven by the SSE feed.
- All motion is tied to real state (SSE `state`, `/stats`, `/events`) — no decoration.
- ⚠️ Full multi-page redesign (a redesigned freelance/agents surface to match) was
  **not** done this pass; the Core is the redesigned "face". Deferred by choice to
  keep this a stabilization pass.

---

## 4. What still needs a live Windows run to sign off

These are correct in code and unit-tested where possible, but only a real machine
with a display, Ollama, and the Windows libraries can confirm end-to-end:

1. App launch for QQ/Doubao/WeChat (Start-Menu/registry resolution is Windows-only).
2. Actual keystrokes landing in Notepad + the clipboard-verify round-trip.
3. llava screen understanding (needs `ollama pull llava:7b`).
4. Real CPU under load (idle CPU should drop; inference spikes are the model).
5. Real bid submission on a logged-in bid platform.

If you run it and something still misbehaves, the loud `/chat` error logging + the
Activity Timeline will now show exactly which path failed — send me that and I can
pinpoint it instead of guessing.

---

## 5. Honest bottom line

I found and fixed several genuine "the new code wasn't actually being used" bugs
(the silent chat fallback, the vision key mismatch, the focus-gate hole, the dead
automation_engine state) — these are the kind of thing that made it "feel
identical" even though source had changed. Those are real, code-level fixes with
tests. The desktop/vision behaviors that depend on Windows APIs and a live display
are written correctly and defensively but I cannot personally confirm them from
here — that's the one thing that genuinely requires your machine, and I've made the
failure paths loud so the next run is diagnosable rather than silent.
