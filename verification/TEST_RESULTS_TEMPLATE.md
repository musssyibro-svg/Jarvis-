# TEST_RESULTS_TEMPLATE.md — fill in after running on the real box

**Date:** _______________  
**Machine:** Windows 10 / 16 GB RAM  
**Ollama version:** _______________  
**Models pulled:** qwen2.5:0.5b [ ] deepseek-r1:1.5b [ ] llava:7b [ ]  

Run command: `python verification/run_all_tests.py`  
Attach: `verification/results/final_report.json`

---

## Results

| Test | Result | Evidence Summary |
|------|--------|-----------------|
| test_health | PASS / FAIL | backend_up=___ ollama_up=___ tables_ok=___ |
| test_hubstaff | PASS / FAIL | jobs_returned=___ fake_detected=___ first_title=___ |
| test_clickworker | PASS / FAIL | tasks=___ fake_ids_found=___ |
| test_zuodao | PASS / FAIL | tasks=___ fake_ids_found=___ |
| test_desktop | PASS / FAIL | notepad_opened=___ notepad_closed=___ typed=___ estop=___ |
| test_browser_profile | PASS / FAIL | cookie_set=___ cookie_persisted=___ |
| test_executor | PASS / FAIL | pending_refused=___ approved_ran=___ status_changed=___ |
| test_llava | PASS / FAIL | path=llava/ocr-fallback keywords_found=___ |
| test_chat_persistence | PASS / FAIL | sqlite_ok=___ frontend_ok=___ refresh_ok=___ |
| test_sse | PASS / FAIL | events_received=___ fields_valid=___ |
| test_playwright_recovery | PASS / FAIL | round1=___ round2=___ cookie_survived=___ |

---

## Artifact Checklist

- [ ] `results/final_report.json` — exists, total/passed/failed populated
- [ ] `results/screenshots/` — at least one screenshot per browser test
- [ ] `results/artifacts/ollama_status_*.json` — Ollama models listed
- [ ] `results/artifacts/processes_*.txt` — process dumps before/after desktop test
- [ ] `results/artifacts/playwright_executor_*.txt` — Playwright log from executor test
- [ ] `results/artifacts/sse_events.json` — raw SSE event list

---

## Desktop Verification

| Action | Result | Evidence |
|--------|--------|---------|
| open_app("notepad") | PASS / FAIL | notepad.exe in process list: YES / NO |
| type_text("JARVIS V8...") | PASS / FAIL | text visible in screenshot: YES / NO |
| close_app("notepad") | PASS / FAIL | notepad.exe gone from process list: YES / NO |
| click(100, 100) | PASS / FAIL | returned success=True: YES / NO |
| emergency_stop blocks input | PASS / FAIL | click returned EMERGENCY STOP error: YES / NO |
| emergency_stop clears | PASS / FAIL | is_estopped() returned False: YES / NO |
| delete_file (no confirm) | PASS / FAIL | needs_confirmation=True: YES / NO |
| delete_file (confirmed) | PASS / FAIL | file removed from disk: YES / NO |

---

## Vision Verification

| | Result |
|-|--------|
| Vision path used | llava-vision / ocr-fallback |
| llava:7b was pulled | YES / NO |
| Keywords found in response | ___ (e.g. "red, square, color") |
| Response snippet | ___ |

---

## Browser Cookie Persistence

| | Result |
|-|--------|
| Session 1 cookie set | YES / NO |
| Session 2 (after restart) cookie present | YES / NO |
| Cookie value matched | YES / NO |

---

## RAM Observations (16 GB box)

| State | RAM Used |
|-------|----------|
| Idle | ___ GB |
| deepseek-r1:1.5b loaded | ___ GB |
| llava:7b during call | ___ GB |
| After llava unloaded | ___ GB |
| Two large models at once? | NEVER / HAPPENED (bug) |

---

## Failures Requiring Follow-Up

| Test | Failure | Next Action |
|------|---------|-------------|
| | | |
| | | |

---

## Notes

_______________________________________________________________
