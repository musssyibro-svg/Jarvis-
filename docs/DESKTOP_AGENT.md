# Desktop Agent

`backend/agents/desktop_agent.py`

Mouse, keyboard, windows, apps. This is the module that makes Jarvis able to do
harm, and the reason the verification rules exist.

---

## The execution loop

`execute_chain(steps, max_retries=2, goal="")`

```
    for each step:
        should_skip?          → record as SKIPPED (you decided, not a failure)
        needs the app in front? → focus it first
        control.checkpoint()  → a pause or cancel lands HERE, between steps
        act
        observe
        verify                → did the world actually change?
        retry (≤ max_retries) → unless the action is in _NO_RETRY
        record                → live_plan + trace + experience
```

Wrapped in `control.run_scope()` so a live cancel can be told apart from a
leftover one.

**A step is done only when it is verified.** `open_app` is confirmed by an
actual window/process check, not by "the launch command returned". If a step
can't be verified after its retries, the chain stops and reports exactly where
and why — never a fake success.

**`_NO_RETRY`** covers input actions. Retrying a keystroke types it twice.

---

## Focus before input — and before *looking*

```python
_INPUT = {"type_text", "compose", "press", "hotkey", "click", "click_text",
          "screenshot", "analyze", "scroll"}
```

`screenshot` and `analyze` are in that set, and their absence was a real bug the
user reported:

> *"it opened qq the first time, but later when I asked it to check my qq
> messages it says no visible unread messages — obviously, because I didn't see
> it open again"*

QQ was **already running**, so `open_app` saw a live window, returned verified,
and never raised it. The screenshot then captured whatever happened to be in
front, and the vision model answered honestly about the wrong window: "no
visible unread messages". Technically true, completely useless, and
indistinguishable from a real answer.

Looking at the screen is an interaction with a specific window, exactly like
typing into one.

**When focus can't be confirmed, the answer carries the doubt.** Typing has a
clipboard read-back to prove it landed; looking has nothing — a screenshot
always succeeds. So an unconfirmed focus prepends a caveat naming the app it
couldn't raise, rather than presenting a description of the wrong window as
fact.

---

## Windows may be in Chinese

**Never match a window by its title.** Notepad is 记事本 and Calculator is
计算器 on this machine. `focus_window` matches by **process name** via
`_process_names_for`. Enforced by `.semgrep/jarvis.yml`
(`jarvis-window-matched-by-title`).

`close_window`, `minimize_window` and `maximize_window` do take a title — they
are given one explicitly by the caller and there is no app to resolve. They
carry a `nosemgrep` with that reason, and they are not in the executor's action
table.

## Launching apps

`open_app` does not shell out to a name and hope. `services/app_resolver.py`
finds the real `.exe` via the Start Menu and the registry, and caches it — that
is what stopped the "Windows cannot find the file qq" dialog.

`services/experience.py` learns how long each app actually takes to show a
window **on this machine**, so the wait is measured rather than guessed. Apps
that habitually fail their first cold start (QQ and similar Electron apps do)
earn one extra attempt, learned from observation.

## The clipboard is the user's

Jarvis uses the clipboard for paste-typing and for reading a field back to
verify what it typed. The user is also using that clipboard.

Every use goes through `_clipboard_snapshot()` / `_clipboard_restore()`. If the
clipboard holds something that cannot be restored — a copied image, files from
Explorer — the guard **refuses to run at all** and the caller falls back to
character-by-character typing. Losing a verification is fine; losing the user's
data is not.

## Emergency stop

`emergency_stop()` blocks all mouse and keyboard actions until cleared. Separate
from `control.pause/cancel`: that one is cooperative and lands between steps,
this one is a hard gate on input.

`pyautogui.FAILSAFE = True` — slamming the mouse into the top-left corner aborts.

## No shell

`run_command` does not use `shell=True`. Job descriptions scraped from freelance
sites are untrusted text sitting next to a logged-in browser; a shell completes
the lethal trifecta. Removed once, enforced by Semgrep so it stays removed.

`close_app` matches by exact process name via psutil, not `pkill -f`. `-f`
matches the full command line of every process, so a short target like `code` or
`notepad` can kill unrelated processes that merely mention it in an argument.

## Failing usefully

`services/experience.classify()` turns an error into `{kind, cause, remedy,
retryable, recovery}`. Every message states the **cause** and the **fix**, not
the symptom.

> "open_app failed" is useless.
> "Windows couldn't find that application — open it manually once so Jarvis can
> learn its real path" is not.

A missing optional dependency is a **skip with an install hint**, never a
failure. Reporting it as a failure sends the user hunting for a bug that isn't
there.

## Learning from what went wrong

After a chain that failed or needed retries, `_learn_from_chain()` hands the
result to `services/reflection.py` on a background thread. Clean runs teach
nothing, and `reflect()` may consult the model — not something to do after every
"open notepad" on a 16 GB machine.

Cancels are skipped: you pressing Stop is not a lesson about the task.
