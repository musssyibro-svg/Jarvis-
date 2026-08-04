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

## Step 5 — This is the important one: memory

**Your PC is out of RAM, and that is the whole reason Jarvis feels slow and
stupid.** Your last report showed 92% used — about 1.3 GB free.

At that level, three things happen at once and they all look like bugs:

- Ollama takes a minute or more to answer the first time, because Windows is
  writing memory to disk. The screen says "Ollama offline". **It isn't offline,
  it's starved.**
- Jarvis falls back to its smallest model, because the good one doesn't fit. So
  the answers get worse.
- Reading your screen stops working — that needs about 5 GB on its own.

Two fixes, in order:

**1. Let `START.bat` delete the models you can't run.** It now does this on its
own. You have `qwen3.5:9b` (~6 GB) and `llama3.1:8b` (~5.5 GB) installed — those
can *never* load on a 16 GB machine with a browser open. They just sit there
tempting Jarvis into trying.

**Keep these three:** `qwen2.5:3b`, `llava:7b`, `nomic-embed-text`.

**2. Close things before you start Jarvis.** Edge tabs and QQ are usually the
biggest. Aim for **3 GB free**.

You'll now see a bar at the top of Jarvis when memory is tight, telling you what
it's costing you and which programs are using the most — plus a **Free up
memory** button that makes Ollama release its models immediately.

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
| `open notepad tell me about yourself` | Same — Notepad can't answer a question, so Jarvis answers it and writes it there. It used to type `me about yourself`. |
| `open notepad, tell me a joke` | Works with a comma too. It used to try to launch an app called "notepad, tell me a joke". |
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
4. Press **Submit N approved** ← **this is the one that actually sends them**
5. Press **Proof** on any row — you'll see the exact text it sent, the page it
   ended on, and a screenshot

**Approving sends nothing.** That's the bit that wasn't clear, and it was my
fault: the old message said "submitting now" when it wasn't. Approve means "yes,
these are fine". Submit is what puts them on the site.

There's now a **"What has actually happened"** box on that page, always visible.
It says things like:

> 3 sent (1 the site didn't confirm — check Proof) · 2 ready to apply by hand
> (job boards have no bid form) · 1 blocked — not logged in

That's the answer to "did it send it?". While it's submitting, the box updates
every two seconds and tells you how many are left.

"Ready to apply by hand" is not a failure. RemoteOK and similar job boards have
no bid form to fill in — the proposal is written and waiting, and you apply
through the link.

Nothing gets submitted without you pressing Submit, unless you tick
"auto-submit" yourself.

---

## Step 10 — Send me one report

After using it for 20–30 minutes:

**Diagnostics → Download full report**

Send me that file. It's dated, so I can tell it's from the new version. The last
three you sent were all the same old file, which is why my fixes looked like
they did nothing.

The report now has two new sections at the end:

**WHERE THE TIME GOES** — every part of Jarvis, ranked by how much time it
actually spent. When something feels slow, this names it. Before, "it feels
slow" was all either of us had.

**FAILED ACTIONS IN FULL** — the complete story behind each failure, including
the Python traceback. Before, a failed action recorded one line, and for one
real crash that line was the single word `DISPLAY`, which meant nothing to
anyone. It never contains your passwords: anything typed is stored as its
length only, so the report stays safe to send.

You can see both live too, without downloading anything — the **Logs** screen
has new **Speed** and **Failures** tabs.

---

## Buttons you now have

- **Pause / Stop** — top strip, on every screen. Never cuts anything in half.
  **Fixed:** one press of Stop used to kill every command for the rest of the
  session. Your last report showed it — you pressed Stop at 10:58, and the next
  five commands over three minutes all died instantly with "Cancelled". Jarvis
  looked completely broken and there was no way to tell why short of restarting
  it. Stop now only stops what was running when you pressed it.
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
purpose and checks it fails honestly. You want 24 or 25 passes.

Errors in that output are normal — it's deliberately breaking things.

---

## Nothing to do here — just so you know it exists

I set up automatic checking on the code itself. **You don't run any of this**
and it changes nothing about how you use Jarvis. It runs on GitHub every time I
change something, and it has already caught three real bugs that I could not
see on my machine:

- **Jarvis crashed on any PC with no screen attached.** A library it uses fails
  differently there, and the code only handled one of the two ways it can fail.
- **Settings silently didn't save on a brand-new install.** If you'd run
  `DOCTOR.bat` on a fresh copy before ever starting Jarvis, anything it saved
  would have been thrown away without a word.
- **A checker told me to install something that was already installed** — the
  same kind of wrong-advice message that has wasted your time before.

The point of it is that "it works on my machine" stops being good enough. Two
of those three would have reached you.

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
