# Planner & Doctor — Quick Guide

Two additions from the second architecture review: long-term project planning
(the one capability the Brain didn't cover) and a reliability self-check.

## Planner — track goals across days, not just one task

Different from what the executor already does. The executor plans *one* task
(open app → verify → retry). The Planner tracks a **goal with many steps over
time**, e.g. "launch MiStore".

**Create a plan**
- Chat: `plan project mistore to launch the refurbished iPhone store`
  (must contain the word "project" so it doesn't collide with freelance "plan
  how to..." requests). Also: `new project ev to research battery PINNs`,
  `create a project called bikestore for the shop`.
- Plans panel: type a name + goal → *Plan it*.

Jarvis breaks the goal into steps automatically (via the local LLM, or a
sensible template per domain — launch / research / freelance — when offline).

**Work a plan**
- Plans panel: click any step to cycle its status
  `todo → doing → done → blocked`. A progress bar tracks completion.
- API: `PATCH /planner/step/{id} {"status":"done","note":"..."}`.

**It shares the Brain's workspace.** A plan named `mistore` and anything you
`remember for mistore:` live under the same project key — knowledge and
execution in one workspace. `GET /planner/project/mistore` and
`GET /brain/documents?project=mistore` both scope to it.

## Doctor — why "it works intermittently" stops being a mystery

Open **Settings** in the UI, or `GET /system/doctor`. It probes every moving
part and, for anything missing, gives the **exact command to fix it**:

- Ollama running? chat/reasoning models pulled?
- Brain semantic search (nomic-embed-text) present? (optional — keyword works without)
- Screenshot (mss/Pillow), desktop control (pyautogui)
- **OCR** — checks the Tesseract *binary*, not just the pip package (the classic trap)
- **Playwright** — checks the chromium *browser*, not just the package
- Free RAM / disk (flags the 16GB squeeze)

Example line when something's missing:
```
✕ OCR (Tesseract)    package OK but BINARY not found
  → Install the Tesseract binary: https://github.com/UB-Mannheim/tesseract/wiki
```

Run it right after `START_JARVIS.bat` on your PC — it's the fastest way to see
what still needs setup versus what's already working.
