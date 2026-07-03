# Jarvis V9 Stage 2 — Structured Perception Changelog

## New capability: structured perception (replaces OCR-text-only)
agents/perception_agent.py extended with:
- observe_browser(headless) -> live Playwright DOM extraction. Returns elements
  [{id, role, tag, text, bbox:[x,y,w,h], clickable, type, name, placeholder, href}].
  JS walks the DOM, skips invisible nodes, flags clickables (A/BUTTON/INPUT/etc,
  role-based, onclick, cursor:pointer, tabindex), caps payload at 400 elements.
- observe_desktop() -> screenshot + pytesseract.image_to_data => per-word boxes
  (OCR WITH coordinates, not text-only). Each element has a bbox.
- find_element(elements, text, role, clickable_only) -> best match + click_point
  (center of bbox). Exact-text match preferred, substring fallback.
- observe() (Stage 1 text-only) preserved unchanged.

## Executor integration
agents/executor_agent.py _act() gained "click_element":
  observe_browser() -> find_element(text) -> desktop_agent.click(click_point).
  Emits visible SSE: "[Executor] Locating 'Submit'..." / "Clicking 'Submit' at (x,y)".
  Returns clean error if perception fails or element not found (no crash, no
  blind click).

## Verified here (deterministic, against mock DOM)
- find_element locates "Submit Application", computes click_point [180,420]
- substring match ("submit"), role filter (textbox), clickable_only skips <p>
- all 4 perception methods present; suite holds 4 PASS / 4 FAIL / 5 SKIP
- test_v9_stage1 now 7/7 (added Stage 2 check)

## Degradation behavior
playwright / pytesseract / PIL imported lazily. Module imports fine without them;
the methods return {ok:False, error:...} when deps/live browser absent. Real
extraction requires a live browser + display on the Windows target.
