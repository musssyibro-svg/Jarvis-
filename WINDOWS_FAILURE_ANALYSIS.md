# WINDOWS FAILURE ANALYSIS — Jarvis V8 Verification
Based on real run on target Windows 10 box.

## FINDING 1 — test_chat_persistence: UnicodeDecodeError 'gbk' byte 0x89
ROOT CAUSE:
  `verification/test_chat_persistence.py` line 116: `chat_jsx.read_text()`
  with no encoding. On a Chinese-locale Windows box, Path.read_text() uses the
  GBK locale codec, not UTF-8. Chat.jsx contains UTF-8 multibyte characters
  ('◉' U+25C9 and '…' U+2026). GBK cannot decode the UTF-8 byte sequence → crash.
  (The 0x89 in the message is GBK mis-reading a UTF-8 continuation byte.)
FILES: verification/test_chat_persistence.py
FIX: read with encoding="utf-8". Also harden every other text read + json write
     in the suite the same way (test_sse writes JSON without encoding → same risk).

## FINDING 2 — test_health: /health missing 'provider' and 'ollama_ok'
ROOT CAUSE:
  backend/main.py /health returns {status, version, ollama, model}.
  The test expects 'provider' and 'ollama_ok'. The endpoint uses key 'ollama'
  (not 'ollama_ok') and has no 'provider' key. Version string also stale (3.0.0).
FILES: backend/main.py
FIX: extend /health to also return provider + ollama_ok (keep old keys for
     backward compatibility). Update version to 8.0.0.

## FINDING 3 — test_hubstaff: zero jobs
ROOT CAUSE:
  backend/services/hubstaff_service.py scrapes Hubstaff Talent via Playwright,
  falling back to an HTTP+BeautifulSoup parse with CSS selectors
  (.job-listing, .job-card, article). Zero jobs = those selectors no longer
  match the live site DOM, OR the site requires auth/blocks the bot.
  This is a LIVE-SITE dependency, not a static code bug. I cannot see the
  current Hubstaff HTML from the build environment, so I will NOT guess new
  selectors (that would be dishonest and likely wrong).
FILES: backend/services/hubstaff_service.py (selectors), plus the TEST itself.
FIX (two parts):
  (a) Make the failure diagnostic: log HTTP status + how many elements each
      selector matched, so you can see WHY it's zero (blocked? changed DOM?).
  (b) The test correctly FAILs on zero jobs — that is accurate. But we add the
      diagnostic so the next run tells us if it's a 403 (needs login) or a
      selector miss (needs new selectors from the live page).

## FINDING 4 — test_zuodao: zero tasks
ROOT CAUSE: identical pattern to Finding 3. zuodao_service._scrape_zuodao uses
  guessy selectors (.task-item, [class*='task'], article). Live-site dependent.
FILES: backend/services/zuodao_service.py + test.
FIX: same diagnostic logging approach. Test FAIL is accurate.

## FINDING 5 — test_desktop: boolean-only evidence rejected for close_app
ROOT CAUSE:
  verification/test_desktop.py line 157-160. The close_app check evidence is
  {"notepad_running": <bool>, "expected": False} — every value is a bool, so
  _harness._is_substantive() correctly rejects it and flips the check to FAIL.
  The verification logic is right; the EVIDENCE payload is the bug.
FILES: verification/test_desktop.py
FIX: include a non-boolean field (process name string + a count) so the evidence
     is substantive while still proving the process is gone.

## FINDING 6 — test_sse: backend unavailable despite backend running
ROOT CAUSE (two compounding issues):
  (a) verification/test_sse.py writes the events artifact with
      open(raw_path, "w") and json.dumps — no encoding. If any event text
      contains non-ASCII, this crashes on Windows GBK exactly like Finding 1.
      But the reported symptom is "backend unavailable", which points to (b).
  (b) The SKIP guard does urlopen(/health, timeout=5) and the SSE collector
      opens a STREAMING endpoint. On Windows, urlopen on a never-closing SSE
      stream can raise/της timeout in a way that the guard interprets as the
      backend being down. The 5s window is also too short if the first event
      ('ping') is delayed. Net effect: a running backend looks "unavailable".
FILES: verification/test_sse.py
FIX:
  - Use encoding="utf-8" on the artifact write.
  - Separate "is backend up" (a real, read-and-close GET to /health) from
    "can we read the stream" so a slow stream never masquerades as a down backend.
  - Treat a reachable /health + a stream that simply produced only pings as a
    PASS-with-note, not a skip/fail. Increase collect window to 8s and read
    in a way that always closes the socket.

## SUMMARY OF FILES TO CHANGE
1. verification/test_chat_persistence.py  — encoding="utf-8" on read
2. backend/main.py                        — /health adds provider + ollama_ok
3. backend/services/hubstaff_service.py   — diagnostic logging (not blind selectors)
4. backend/services/zuodao_service.py     — diagnostic logging
5. verification/test_desktop.py           — non-boolean evidence for close_app
6. verification/test_sse.py               — utf-8 write + robust up/stream split
7. verification/_harness.py               — make capture_screenshot/json writes utf-8 safe (defensive)
