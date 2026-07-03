# PRE-RELEASE AUDIT — Jarvis V8
Date: 2026-06-17
Verdict: NOT RELEASE READY (7 issues, 3 blockers)

---

## ISSUE SEVERITY RANKING

### BLOCKER (must fix before release)

**B1 — start.bat runs uvicorn from wrong directory**
File: `start.bat` (root level)
Problem: `cd /d "%~dp0"` sets CWD to project root. Then runs
`python -m uvicorn main:app` but `main.py` lives in `backend/`, not root.
Will fail with `ModuleNotFoundError: No module named 'main'` on Windows.
Fix: add `cd backend` before the uvicorn line, or rename the bat to cd correctly.

**B2 — start.bat version string is wrong ("V4")**
File: `start.bat`
Problem: Title says "JARVIS OS V4 - AUTONOMOUS FREELANCE AGENT".
Misleading to the user and fails the release identity check.
Fix: update to V8.

**B3 — Hardcoded `http://127.0.0.1:8000` in 12 frontend files**
Files: `Sidebar.jsx`, `Chat.jsx`, `Tasks.jsx`, `Jobs.jsx`, `AutoMode.jsx`,
       `Analytics.jsx`, `Workspace.jsx`, `Settings.jsx`, `Dashboard.jsx`,
       `Messages.jsx`, `Notes.jsx`, `Proposals.jsx`
Problem: `config.js` exists with `import.meta.env.VITE_API_URL` support, but
only `Agents.jsx` imports it. All other pages define `const API = 'http://127.0.0.1:8000'`
locally. If the user changes ports or deploys remotely, 12 pages break.
Fix: replace local `const API` with `import { API } from '../config.js'` in each file.

---

### HIGH (should fix before release)

**H1 — RAM monitoring missing from test_hubstaff, test_clickworker, test_zuodao, test_health**
Files: those 4 test files
Problem: All other heavy tests (executor, llava, desktop, browser, chat, sse,
playwright_recovery) capture RAM snapshots. The scraper tests (which load
Playwright + network) and health check (which probes Ollama) have zero RAM
monitoring. Inconsistent with the stated requirement.
Fix: add `ram_snapshot` calls at start/before-scrape/end in all 4 files.

**H2 — `requirements.txt` header says "Jarvis VNext (V5)"**
File: `backend/requirements.txt`
Problem: Stale version string. Minor but unprofessional and confusing.
Fix: update header to "Jarvis V8".

**H3 — `backend/jarvis.db` committed to the project with 0 tables**
File: `backend/jarvis.db`
Problem: An empty database file is checked in. On Windows, `init_db()` creates
tables at startup. The committed empty DB could confuse users who see it and
assume it's the real database. It will also cause `test_health` to report DB
exists but 0 tables (technically correct but misleading).
Fix: delete `backend/jarvis.db` from the package. Add it to a `.gitignore`.
`init_db()` will create it fresh on first start.

---

### LOW (acceptable for release, fix in next patch)

**L1 — `WeWorkRemotelytPlatform` typo (extra 't') across 3 files**
Files: `platforms/weworkremotely.py`, `agents/scout_agent.py`,
       `services/automation_engine.py`
Problem: Class name has a typo (`WeWorkRemotelyt` instead of `WeWorkRemotely`).
Consistent across all three files so it doesn't cause a runtime error, but it
is wrong and will confuse future contributors.
Fix: rename consistently in all three files.

**L2 — `config.js` comment says "V5"**
File: `frontend/src/config.js`
Problem: Comment reads `// src/config.js — central API config (V5)`. Stale.
Fix: update comment to V8.

---

## AUDIT DETAIL — Each Requirement

### 1. RAM Monitoring
- ✓ test_desktop: 7 RAM calls, saved as artifact
- ✓ test_browser_profile: 6 RAM calls, saved as artifact
- ✓ test_executor: 9 RAM calls, saved as artifact
- ✓ test_llava: 9 RAM calls, saved as artifact (incl. before/after llava load)
- ✓ test_chat_persistence: 9 RAM calls
- ✓ test_sse: 6 RAM calls
- ✓ test_playwright_recovery: 6 RAM calls
- ✗ test_hubstaff: 0 RAM calls (issue H1)
- ✗ test_clickworker: 0 RAM calls (issue H1)
- ✗ test_zuodao: 0 RAM calls (issue H1)
- ✗ test_health: 0 RAM calls (issue H1)

### 2. Environment-dependent SKIP
- ✓ test_desktop: SKIP when pyautogui absent — confirmed working
- ✓ test_browser_profile: SKIP when playwright/network absent
- ✓ test_executor: SKIP when playwright absent
- ✓ test_llava: SKIP when Ollama unreachable
- ✓ test_chat_persistence: SKIP when playwright absent or frontend down
- ✓ test_sse: SKIP when backend not running
- ✓ test_playwright_recovery: SKIP when playwright absent
- ✓ test_hubstaff/clickworker/zuodao: FAIL (not SKIP) on zero results — CORRECT
  (they have Playwright; zero results = site unavailable or not logged in = real FAIL)
- ✓ test_health: FAIL when backend/Ollama down — CORRECT (health test should FAIL)

### 3. Reporting
- ✓ skip_reason in final_report.json for all 5 SKIP tests
- ✓ skip_reason in per-test JSON reports
- ✓ boolean-only evidence rejected by _harness
- ✓ screenshots captured in browser profile + playwright recovery tests
- ✓ process dumps captured before/after desktop and executor tests
- ✓ Ollama status dumps saved as artifacts

### 4. Executor verification
- ✓ PENDING items refused (safety gate confirmed)
- ✓ STATE.emit patched to capture live feed events
- ✓ Feed events show "Opening job page", "Filling bid description" — navigation proven
- ✓ Queue status changes from 'approved' to 'failed' after attempt
- ✓ executor_nav artifact saved with stdout + feed events

### 5. Cleanup
- ✓ register_temp() + atexit cleanup for temp DBs
- ✓ cleanup_old_artifacts(days) available
- ✓ All temp-using tests call register_temp
- ✗ backend/jarvis.db empty file should not be in package (issue H3)

### 6. File structure
- ✓ All 13 verification Python files compile
- ✓ All 52 backend Python files compile
- ✓ All 14 frontend JSX/JS files: balanced braces + resolved imports
- ✓ No duplicate route paths
- ✓ platforms/ imported correctly by scout_agent and automation_engine
- ✗ B1: start.bat wrong CWD for uvicorn
- ✗ B2: start.bat says "V4"
- ✗ B3: 12 pages hardcode API URL
- ✗ L1: WeWorkRemotelyt typo

### 7. Release readiness — Windows 10 / 16GB
- ✓ Approved models (qwen2.5:0.5b, deepseek-r1:1.5b, llava:7b) correctly configured
- ✓ RAM constraints enforced: single large model lock, llava lazy-load + unload
- ✓ Emergency stop implemented and verified
- ✓ requirements.txt complete with all V8 deps
- ✗ B1 would cause immediate startup failure on Windows

---

## FILES REQUIRING MODIFICATION

| # | File | Severity | Change |
|---|------|----------|--------|
| 1 | `start.bat` | BLOCKER | Fix cd to backend/, fix version string |
| 2 | `frontend/src/components/Sidebar.jsx` | BLOCKER | Import API from config.js |
| 3 | `frontend/src/pages/Chat.jsx` | BLOCKER | Import API from config.js |
| 4 | `frontend/src/pages/Tasks.jsx` | BLOCKER | Import API from config.js |
| 5 | `frontend/src/pages/Jobs.jsx` | BLOCKER | Import API from config.js |
| 6 | `frontend/src/pages/AutoMode.jsx` | BLOCKER | Import API from config.js |
| 7 | `frontend/src/pages/Analytics.jsx` | BLOCKER | Import API from config.js |
| 8 | `frontend/src/pages/Workspace.jsx` | BLOCKER | Import API from config.js |
| 9 | `frontend/src/pages/Settings.jsx` | BLOCKER | Import API from config.js |
| 10 | `frontend/src/pages/Dashboard.jsx` | BLOCKER | Import API from config.js |
| 11 | `frontend/src/pages/Messages.jsx` | BLOCKER | Import API from config.js |
| 12 | `frontend/src/pages/Notes.jsx` | BLOCKER | Import API from config.js |
| 13 | `frontend/src/pages/Proposals.jsx` | BLOCKER | Import API from config.js |
| 14 | `verification/test_hubstaff.py` | HIGH | Add RAM monitoring |
| 15 | `verification/test_clickworker.py` | HIGH | Add RAM monitoring |
| 16 | `verification/test_zuodao.py` | HIGH | Add RAM monitoring |
| 17 | `verification/test_health.py` | HIGH | Add RAM monitoring |
| 18 | `backend/requirements.txt` | HIGH | Update version header |
| 19 | `backend/jarvis.db` | HIGH | DELETE from package |
| 20 | `platforms/weworkremotely.py` | LOW | Fix typo WeWorkRemotelyt |
| 21 | `agents/scout_agent.py` | LOW | Fix typo WeWorkRemotelyt |
| 22 | `services/automation_engine.py` | LOW | Fix typo WeWorkRemotelyt |
| 23 | `frontend/src/config.js` | LOW | Update comment to V8 |

---

## VERDICT: NOT RELEASE READY

Blockers: 3 (B1 start.bat, B2 version string, B3 hardcoded URLs)
Must be fixed before packaging the final ZIP.
