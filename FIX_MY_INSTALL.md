# It won't start — do this

Four separate things went wrong. The first one was mine, and it made the other
three impossible to diagnose because the launcher printed error messages that
were simply untrue.

Run everything below from a normal Command Prompt. Your project is on D:, so
every path starts with `cd /d D:\jarvis_v9`.

---

## Step 1 — get the fixed files

```
cd /d D:\jarvis_v9
git pull
```

If `git pull` complains that `.bat` files have local changes, they're the broken
ones — throw them away and take the new ones:

```
git checkout -- *.bat
git pull
```

**Not using git?** Then delete every `.bat` in `D:\jarvis_v9` and download them
again from GitHub. They have to come down fresh — this is the whole fix.

---

## Step 2 — undo the npm accident

`npm init -y` was run in `D:\jarvis_v9`. That created a `package.json` there
which is **not** the UI — the real one is in `frontend\`. It's why `npm run dev`
started an empty project, took port 5173, and pushed the real UI to 5175.

```
cd /d D:\jarvis_v9
del package.json package-lock.json
rmdir /s /q node_modules
```

Do **not** delete `frontend\package.json` or `frontend\node_modules` — those are
the real ones and they're fine.

Then close every open Command Prompt window running `npm run dev`, or:

```
taskkill /f /im node.exe
```

---

## Step 3 — check everything at once

```
cd /d D:\jarvis_v9
DOCTOR.bat
```

This is new. It checks Python, every package, Node, Ollama, the Playwright
browser, Tesseract, ports, line endings, and the stray package.json — then
prints exactly what to type for each problem, in order. Work down its list.

---

## Step 4 — the browser download

Your log shows this failing repeatedly:

```
playwright install chrome        <-- this can NEVER work from China
```

`chrome` fetches Google's branded MSI from a Google server using a PowerShell
script that **ignores** `PLAYWRIGHT_DOWNLOAD_HOST`. No mirror can help it. That
is why you got 无法连接到远程服务器 every time, even after setting the mirror.

Use `chromium` instead — that one does honour the mirror:

```
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
python -m playwright install chromium
```

(You also ran a bare `playwright install`, which returned instantly with no
output. That usually means it had nothing to do — DOCTOR.bat will tell you
whether chromium is actually on disk.)

---

## Step 5 — start it

```
cd /d D:\jarvis_v9
START_JARVIS.bat
```

Or by hand, in two windows:

```
:: window 1
cd /d D:\jarvis_v9\backend
python main.py

:: window 2
cd /d D:\jarvis_v9\frontend
npm run dev
```

`python main.py` now actually starts the server. Before, it imported the app and
exited without serving — no error, no output, which looked like a crash. That's
fixed.

Two commands that were never going to work, from your log:
- `python main.py` **in the project root** — main.py is in `backend\`
- `python app.py` — there is no app.py; the file is `main.py`

---

## Step 6 — Phase 0

```
cd /d D:\jarvis_v9
RUN_FAILURE_TEST.bat
```

---

## What was actually broken

**1. My bug — batch files had Unix line endings.**
Every `.bat` was written on Linux. cmd.exe parses batch files by byte position,
and with LF-only endings it loses its place and eats the first characters of
lines. That produced your output exactly:

| you saw | it was trying to run |
|---|---|
| `'tle' 不是内部或外部命令` | `title` |
| `'tlocal' 不是内部或外部命令` | `setlocal` |
| `'ho' / 'cho.' 不是内部或外部命令` | `echo` |
| `'JARVIS' 不是内部或外部命令` | `REM  JARVIS - ...` |
| **`[X] Python not found on PATH`** | **the check itself was mangled** |

That last line is the important one. Python was installed correctly the whole
time — you proved it with `python --version`. The launcher was lying because its
own code had been chewed up. Fixed, plus `.gitattributes` so git can never hand
you LF `.bat` files again, and the em-dashes are gone (they render as mojibake
in a Chinese-locale console).

**2. `python main.py` did nothing.** No `if __name__ == "__main__"` block, so it
loaded and quit silently. Now it starts the server and tells you if you're in
the wrong folder.

**3. CORS only allowed port 5173.** With stale dev servers holding 5173 and
5174, Vite moved you to 5175 — the page would have loaded and then every API
call would have been silently blocked. Any localhost port is allowed now.

**4. `playwright install chrome`** can't use a mirror. Covered in step 4.

---

## Send me this if it still won't go

```
cd /d D:\jarvis_v9
DOCTOR.bat > doctor_output.txt
```

`doctor_output.txt` tells me your exact state. Paste it, or the console output
of whatever fails.
