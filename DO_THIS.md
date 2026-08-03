# Do this

Plain steps. No explanations unless something breaks.

**Stay in `D:\jarvis_v9`.** Don't make a new folder. Everything below works in
the one you already have.

---

## Step 1 — Update (2 min)

Open `D:\jarvis_v9` in File Explorer. **Double-click `UPDATE.bat`.**

That's it. It downloads the newest version and puts it in place. It does **not**
touch your database, your logins, your settings or your saved token.

You don't need git. You don't need to clone anything. Last time the clone
failed because GitHub timed out *and* because the backticks from my message got
pasted into the command — that's on me, and `UPDATE.bat` removes the whole
problem.

If `UPDATE.bat` says every download source failed, your network can't reach
GitHub right now. Wait a few minutes and run it again.

---

## Step 2 — There is now only ONE launcher

You ran `START_JARVIS.bat`. That was the old V8 one — it pulled the wrong
models and never installed the UI, which is why `npm run dev` then died with
*"Cannot find module 'vite'"*.

I deleted it, along with `start.bat`, `start_frontend.bat` and
`RUN_VALIDATION.bat`. Four launchers, all subtly different, all wrong.

**The only one now is `START.bat`.** If you double-click the old name out of
habit, it just runs `START.bat` for you.

---

## Step 3 — Start it (first run: 10–20 min)

**Double-click `START.bat`.**

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
cd /d D:\jarvis_v9
```
```
DOCTOR.bat > doctor_output.txt
```

**If the UI window shows "Cannot find module 'vite'"** — `START.bat` now
installs it for you automatically. If it still happens, run:

```
cd /d D:\jarvis_v9\frontend
```
```
npm install --registry=https://registry.npmmirror.com
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

## Step 6 — Look at the new screens first

There are four now: **Planner**, **Memory**, **Logs**, and a rebuilt
**Settings**.

- **Logs** — every decision with a timestamp and a reason. Three tabs: the live
  feed (filter by subsystem, or "problems only"), the exact code path each
  request took, and how confident it was in each finished run. This is what you
  send me instead of describing what happened.
- **Memory** — everything Jarvis knows, in one editable place. Facts it always
  has in mind, a search box that runs the *real* retrieval so you can see what a
  question would pull up, and a way to write down longer things (your rates,
  how you like proposals worded).



**Settings** now shows five things, and the important one is at the bottom:

- **About you** — what Jarvis remembers about you. It fills itself in on first
  start (it works out that you're in China and that you have no Chrome). Add
  anything else you want it to stop asking about.
- **This PC** — what it actually found on your machine, and what that means.
  This is where "why is vision slow" gets answered: no GPU, so it runs on the
  CPU.
- **Behaviour** — models, search engine, and which app to use for what.
- **Which AI answers what** — new. Everything still runs on your own PC and
  nothing is sent anywhere. But if you ever want to paste in a DeepSeek, GLM,
  Kimi or OpenRouter key, you can now pick which *kind* of thinking uses it —
  e.g. planning on DeepSeek, everything else local. If a paid one fails or runs
  out of credit, Jarvis drops back to your local model instead of stopping.
  Keys are stored on your PC and never appear in the reports you send me.
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
| `simulate applying for jobs` | What a freelance run *would* do. Sends nothing. |

Before running anything risky you can check it first. Go to **Planner → Check a
command first**, type the sentence, and press either:

- **Show plan** — the steps it would run.
- **Simulate** — the steps *plus* what each one touches, how long it would take
  on your PC, and what would stop it. Runs nothing at all.

You can do the same in chat: `what would you do if I say open notepad and write
about yourself`. And before letting it loose on freelancing: `simulate applying
for jobs` tells you which sites it would search, how many proposals it would
write, and whether it would submit them — without scanning or sending anything.

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
cd /d D:\jarvis_v9\backend
```
```
pip install fastmcp
```
```
python mcp_server.py --http
```

It prints a token. Point Cherry Studio, Claude Desktop or Cline at
`http://127.0.0.1:8765/mcp` and add that token as a header called
`X-Jarvis-Token`.

They get fifteen commands — search the web, control the desktop, find freelance
jobs, look at the screen, ask why something failed, and simulate anything first.
Jarvis stays exactly as it is; this is just another way to talk to it.

It only listens on your own PC, and now it needs the token, so nothing else can
drive it even from this machine.

---

## Optional: check it recovers from failure

Double-click **`RUN_FAILURE_TEST.bat`**. Takes 2 minutes. Breaks Jarvis on
purpose and checks it fails honestly. You want 18 or 19 passes.

Errors in that output are normal — it's deliberately breaking things.

---

## One safety note

Jarvis can type on your keyboard and use a browser that's already signed in to
your accounts. Keep it on `127.0.0.1` — that's the default and you don't have to
do anything.

If you ever want the freelance engine running but nothing touching your desktop,
put this line in `D:\jarvis_v9\backend\.env`:

```
DESKTOP_CONTROL_ENABLED=0
```
