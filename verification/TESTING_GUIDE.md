# TESTING_GUIDE.md — Jarvis V8 Verification Suite (Revised)

Addresses: DeepSeek technical audit, Grok UX review, Doubao QA review.

---

## Setup

### 1. Install Python dependencies
```
cd backend
pip install -r requirements.txt
pip install psutil          # process verification
pip install pyautogui       # desktop live input tests
pip install pygetwindow     # window management tests
pip install mss Pillow      # screenshot capture
```

### 2. Install Playwright browsers
```
playwright install chromium msedge
```

### 3. Pull Ollama models
```
ollama serve
ollama pull qwen2.5:0.5b
ollama pull deepseek-r1:1.5b
ollama pull llava:7b          # only needed for real vision path
```

### 4. Start the backend (separate terminal)
```
cd backend
python -m uvicorn main:app --reload --port 8000
```

### 5. Start the frontend (separate terminal, for chat persistence test)
```
cd frontend
npm install
npm run dev
```

---

## Running Tests

### Run everything
```
cd verification
python run_all_tests.py
```

### Skip Playwright/network tests (fast check)
```
python run_all_tests.py --quick
```

### Run a single test
```
python test_health.py
python test_desktop.py
python test_llava.py
```

---

## Test Descriptions

| Test | What it proves | Needs |
|------|---------------|-------|
| **test_health** | Backend up, Ollama running, DB tables present, dirs exist | backend running |
| **test_hubstaff** | Scraper returns ≥1 real job; fake-data detection | Playwright + network |
| **test_clickworker** | Real tasks returned; hardcoded IDs detected | live site |
| **test_zuodao** | Real tasks returned; hardcoded IDs detected | live site |
| **test_desktop** | open/close notepad; process verification via psutil/tasklist; type_text; file ops; estop | pyautogui + display |
| **test_browser_profile** | Launches browser, writes cookie, closes, reopens same profile, verifies cookie persists | Playwright + network |
| **test_executor** | Refuses PENDING items; runs APPROVED item path; Playwright launch attempt; queue status changes | Playwright |
| **test_llava** | Known red-square image sent to llava; keyword check ("red","square","color"); OCR fallback if absent | llava:7b OR Ollama |
| **test_chat_persistence** | SQLite restart round-trip; localStorage static check; Playwright browser refresh | frontend running |
| **test_sse** | SSE /orchestrator/feed reachable; events parsed; fields validated | backend running |
| **test_playwright_recovery** | Browser crash-recovery cycle; cookie survives; reconnect works | Playwright + network |

---

## Reading Results

Every test writes `verification/results/<test>.json`. Structure:
```json
{
  "test": "test_desktop",
  "result": "PASS | FAIL | SKIP",
  "checks": [
    {
      "label": "write_file creates real file on disk",
      "ok": true,
      "evidence": {"path": "/tmp/...", "size_bytes": 20},
      "substantive_evidence": true,
      "error": null
    }
  ],
  "artifacts": ["results/screenshots/...", "results/artifacts/..."],
  "logs": [...]
}
```

A test **cannot PASS** unless:
- Every check passed, AND
- At least one check has substantive evidence (not boolean-only)

---

## Artifacts

All artifacts land in `verification/results/`:

| Folder | Contents |
|--------|----------|
| `results/screenshots/` | Screenshots from desktop + browser tests |
| `results/artifacts/` | Process dumps, Playwright logs, Ollama status dumps |
| `results/*.json` | Per-test JSON reports |
| `results/final_report.json` | Combined suite report |

---

## Fake Data Detection

`test_hubstaff`, `test_clickworker`, `test_zuodao` all check for:
- Known hardcoded task/job IDs (`cw_cat_*`, `zd_cat_*`)
- `is_sample: true` flag
- `source: sample_fallback` field
- Placeholder strings ("fake", "sample", "lorem ipsum", etc.)

If any of these appear, the test FAILs with the specific item flagged.

---

## Expected Results (dev environment, no network/display)

When run in a sandboxed Linux environment without network/Ollama/display:

| Test | Expected |
|------|----------|
| test_health | FAIL (backend not running) |
| test_hubstaff | FAIL (no Playwright/network) |
| test_clickworker | FAIL (no live site) |
| test_zuodao | FAIL (no live site) |
| test_desktop | FAIL on live input (no pyautogui); file ops + estop PASS |
| test_browser_profile | FAIL (no Playwright) |
| test_executor | PARTIAL — safety gate passes; Playwright fails |
| test_llava | PASS (logic checks pass; llava absent = clean refusal) |
| test_chat_persistence | PARTIAL — SQLite + static checks pass; Playwright skipped |
| test_sse | FAIL (backend not running) |
| test_playwright_recovery | FAIL (no Playwright) |

On your **Windows 10 box with everything installed**: all tests should PASS.

---

## Honest Limitations

- `test_desktop` live input (open/close/type) cannot be auto-asserted in a
  headless CI environment — it requires a real desktop session with pyautogui.
- `test_chat_persistence` Playwright refresh requires both backend and frontend
  running simultaneously.
- Scraper tests depend on the live sites being accessible and your session being
  logged in. Site layout changes may break selectors.
