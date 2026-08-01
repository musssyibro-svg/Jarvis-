# Do this

Plain steps. No explanations unless something breaks.

---

## Step 1 — Get the new version (5 min)

Open **Git CMD** from your Start Menu. Paste these **one line at a time**:

```
cd /d D:\
```
```
git clone -b claude/jarvis-automation-rebuild-37xvhr https://github.com/musssyibro-svg/Jarvis-.git jarvis_new
```

If `D:\jarvis_new` already exists from before, do this instead:

```
cd /d D:\jarvis_new
```
```
git pull
```

**If git is slow or blocked:** go to the repo on GitHub in your browser, switch
the branch to `claude/jarvis-automation-rebuild-37xvhr`, click **Code → Download
ZIP**, and extract to `D:\jarvis_new`.

---

## Step 2 — Bring your old data across (1 min, optional)

Keeps your learned timings and any website logins. One line at a time:

```
copy D:\jarvis_v9\backend\jarvis.db D:\jarvis_new\backend\
```
```
xcopy /e /i /y D:\jarvis_v9\backend\browser-profile D:\jarvis_new\backend\browser-profile
```

Don't delete `D:\jarvis_v9` yet. Keep it until the new one works.

---

## Step 3 — Start it (first run: 10–20 min)

Open `D:\jarvis_new` in File Explorer. **Double-click `START.bat`.**

That's it. It installs everything missing — Python packages, the automation
browser, UI packages, AI models — then starts Jarvis and opens your browser.

The first run is slow because it's downloading. Later runs take seconds.

**Leave it alone while it works.** Two black windows will open and stay open.
Closing them stops Jarvis.

---

## Step 4 — If it doesn't start

Double-click **`DOCTOR.bat`**.

It prints a numbered list of exactly what to type. Work down the list, then run
`START.bat` again.

If you still can't get it going, run this and send me the file:

```
cd /d D:\jarvis_new
```
```
DOCTOR.bat > doctor_output.txt
```

---

## Step 5 — Free up disk space (you were at 1.2 GB)

`START.bat` does this for you automatically. If you want to do it by hand:

```
ollama rm qwen2.5:0.5b
```
```
ollama rm qwen:latest
```
```
ollama rm qwen2:7b
```
```
ollama rm deepseek-r1:latest
```

**Keep these three:** `qwen2.5:3b`, `llava:7b`, `nomic-embed-text`.

---

## Step 6 — Look at the two new screens first

**Settings** now shows five things, and the important one is at the bottom:

- **About you** — what Jarvis remembers about you. It fills itself in on first
  start (it works out that you're in China and that you have no Chrome). Add
  anything else you want it to stop asking about.
- **This PC** — what it actually found on your machine, and what that means.
  This is where "why is vision slow" gets answered: no GPU, so it runs on the
  CPU.
- **Behaviour** — models, search engine, and which app to use for what.
- **Security** — what's protecting it right now.
- **What's actually in effect** — every setting with the value the running
  system is *really* using, and where that value came from. **If you change
  something and nothing happens, this screen tells you why.** That was the old
  "I set it, I saved it, nothing changed" problem.

**Planner** is the new screen. It shows the plan and what's happening on the
same page. You get:

- every step, live, with a tick or a cross and how long it took
- **Skip** a step you don't want, **Retry** one that failed, **Stop** everything
- **Why** — the full chain of what happened, the cause, and the fix
- **Confidence** — how sure it was about recent runs, and what it changed about
  itself as a result
- **Watch me do it** — the record button (see step 8)

---

## Step 7 — Try these, in this order

Type them into the Jarvis chat box.

| Say this | You should get |
|---|---|
| `open notepad and type hello` | Notepad opens, types `hello` |
| `open notepad and write about yourself` | Notepad opens with **real written text**, not the words "about yourself" |
| `open browser and search BMW M4` | **Edge** opens (not Chrome), searching Bing |
| `open browser and search BMW M4 and analyze the page` | Searches only `BMW M4`, then describes it |
| `open notepad, then type hello, then save it` | Three separate steps, in order |
| `send Ahmed a message on qq saying hello` | QQ opens, finds Ahmed, types hello |
| `what's on my screen` | Describes your screen in **under a minute** |
| `why?` | The full step chain of what just happened |
| `remember that I am a freelance developer` | It saves that and stops asking |

Before running anything risky you can check it first: go to **Planner → Check a
command first**, type the sentence, press **Show plan**. It shows you exactly
what it will do, without doing it.

If any of those misbehave, tell me **which one** and what it did instead.

---

## Step 8 — Teach it something by showing it

This is the new one.

1. Go to **Planner**
2. Type a name in the box, e.g. `apply for a job`
3. Press **Watch me do it**
4. Do the task yourself, normally, once
5. Press **Stop**

It shows you the steps it learned. Then say `run my apply for a job` in chat and
it does it.

You can also just say `watch me apply for a job` in chat, and `that's it` when
you're finished.

**Your passwords are never recorded.** If you type into a login box while it's
watching, it records "there's a login here" and nothing else. On replay it uses
your saved login from the encrypted vault, or stops and asks you.

---

## Step 9 — The freelance part

Go to **Earn**.

1. Press **Start earning**
2. Wait for it to find jobs and write proposals
3. Press **Approve all N drafts**
4. Press **Submit N approved**
5. Press **Proof** on any row — you'll see the exact text it sent, the page it
   ended on, and a screenshot

Nothing gets submitted without you pressing Approve, unless you tick
"auto-submit" yourself.

---

## Step 10 — Send me one report

After using it for 20–30 minutes:

**Diagnostics → Download full report**

Send me that file. It's dated, so I can tell it's from the new version. The last
three you sent were all the same old file, which is why my fixes looked like
they did nothing.

---

## Buttons you now have

- **Pause / Stop** — top strip, on every screen. Never cuts anything in half.
- **Skip / Retry** — per step, on the Planner screen.
- **Why?** — top strip and Planner. The full chain, not "Failed".
- **Show plan** — Planner. See what a command will do before it does it.
- **Watch me do it** — Planner. Teach by demonstrating.
- **Proof** — on every freelance row. Shows what was actually sent.
- **Approve all / Submit approved** — on the Earn page.

---

## Optional: let ChatGPT or Claude Desktop control Jarvis

Not needed. Only do this if you want it.

```
cd /d D:\jarvis_new\backend
```
```
pip install fastmcp
```
```
python mcp_server.py --http
```

Then point Cherry Studio, Claude Desktop or Cline at `http://127.0.0.1:8765/mcp`.

They get fourteen commands — search the web, control the desktop, find freelance
jobs, look at the screen, ask why something failed. Jarvis stays exactly as it
is; this is just another way to talk to it.

It only listens on your own PC. Nothing on your network can reach it.

---

## Optional: check it recovers from failure

Double-click **`RUN_FAILURE_TEST.bat`**. Takes 2 minutes. Breaks Jarvis on
purpose and checks it fails honestly. You want 14 or 15 passes.

Errors in that output are normal — it's deliberately breaking things.

---

## One safety note

Jarvis can type on your keyboard and use a browser that's already signed in to
your accounts. Keep it on `127.0.0.1` — that's the default and you don't have to
do anything.

If you ever want the freelance engine running but nothing touching your desktop,
put this line in `D:\jarvis_new\backend\.env`:

```
DESKTOP_CONTROL_ENABLED=0
```
