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

## Step 6 — Try these, in this order

Type them into the Jarvis chat box.

| Say this | You should get |
|---|---|
| `open notepad and type hello` | Notepad opens, types `hello` |
| `open notepad and write about yourself` | Notepad opens with **real written text**, not the words "about yourself" |
| `open browser and search BMW M4` | **Edge** opens (not Chrome), searching Bing |
| `open browser and search BMW M4 and analyze the page` | Searches only `BMW M4`, then describes the page |
| `send Ahmed a message on qq saying hello` | QQ opens, finds Ahmed, types hello |
| `what's on my screen` | Describes your screen in **under a minute** |

If any of those misbehave, tell me **which one** and what it did instead.

---

## Step 7 — The freelance part

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

## Step 8 — Send me one report

After using it for 20–30 minutes:

**Diagnostics → Download full report**

Send me that file. It's dated, so I can tell it's from the new version. The last
three you sent were all the same old file, which is why my fixes looked like
they did nothing.

---

## Buttons you now have

- **Pause / Stop** — top strip, on every screen. Never cuts anything in half.
- **Why?** — top strip. Tells you what it's doing and why.
- **Proof** — on every freelance row. Shows what was actually sent.
- **Approve all / Submit approved** — on the Earn page.

---

## Optional: check it recovers from failure

Double-click **`RUN_FAILURE_TEST.bat`**. Takes 2 minutes. Breaks Jarvis on
purpose and checks it fails honestly. You want 9 or 10 passes.

Errors in that output are normal — it's deliberately breaking things.
