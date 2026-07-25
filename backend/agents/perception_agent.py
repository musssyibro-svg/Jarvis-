"""
agents/perception_agent.py — V9 Stage 2 structured perception.

Stage 1 (text only) is preserved as observe(). Stage 2 ADDS:
  - observe_browser(): structured DOM elements from the live Playwright page —
    role, text, bbox [x,y,w,h], clickable, plus selector + attributes.
  - observe_desktop(): OCR WITH bounding boxes via pytesseract.image_to_data
    (not OCR-text-only), so desktop targets have coordinates.
  - find_element(): query structured elements by role/text for the Executor.

All heavy deps (playwright, pytesseract, PIL) are imported lazily and degrade
cleanly when absent, so this module imports fine in any environment. Real
extraction obviously requires a live browser / display on the target machine.
"""
from agents.base_agent import BaseAgent


# JS evaluated in the page to extract a structured, clickable-aware element tree.
_DOM_EXTRACT_JS = r"""
() => {
  const CLICKABLE = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA','LABEL','SUMMARY']);
  const ROLE_CLICKABLE = new Set(['button','link','checkbox','radio','tab','menuitem','textbox']);
  const out = [];
  const nodes = document.querySelectorAll('*');
  let id = 0;
  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;            // skip invisible
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const tag = el.tagName;
    const role = el.getAttribute('role') || tag.toLowerCase();
    const text = (el.innerText || el.value || el.getAttribute('aria-label')
                  || el.getAttribute('placeholder') || '').trim().slice(0, 120);
    const clickable = CLICKABLE.has(tag) || ROLE_CLICKABLE.has(role)
                      || el.onclick != null || style.cursor === 'pointer'
                      || el.getAttribute('tabindex') === '0';
    // only keep elements that are clickable OR carry meaningful text
    if (!clickable && !text) continue;
    out.push({
      id: id++,
      role: role,
      tag: tag,
      text: text,
      bbox: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      clickable: !!clickable,
      type: el.getAttribute('type') || null,
      name: el.getAttribute('name') || null,
      placeholder: el.getAttribute('placeholder') || null,
      href: el.getAttribute('href') || null,
    });
    if (id > 400) break;   // cap payload
  }
  return out;
}
"""


class PerceptionAgent(BaseAgent):
    name = "perception"
    _available_cache = None  # None = unprobed; True/False after first check

    def available(self) -> bool:
        """
        Cheap, cached capability probe: can this machine actually perceive the
        screen? Checks the Tesseract BINARY (not just the pip package — the
        package installs via requirements.txt while the binary needs a separate
        Windows installer), then falls back to checking for a vision model.
        """
        if PerceptionAgent._available_cache is not None:
            return PerceptionAgent._available_cache
        ok = False
        try:
            import agents.vision_agent  # noqa: F401 — configures tesseract_cmd path
            import pytesseract
            pytesseract.get_tesseract_version()  # runs the binary; raises if absent
            ok = True
        except Exception:
            try:
                from services.ollama_manager import validate_model, VISION_MODEL
                ok = bool(validate_model(VISION_MODEL).get("valid"))
            except Exception:
                ok = False
        PerceptionAgent._available_cache = ok
        return ok

    # ── Stage 1 (preserved): text-only ─────────────────────────────────────────
    def observe(self, question: str = "") -> dict:
        """Stage 1 schema: {ok, screen_text, method, error, elements=[]}."""
        try:
            from agents.vision_agent import analyze_screen
            r = analyze_screen(question or "Describe the current screen state")
            # analyze_screen returns the LLM result under 'answer'/'ai_answer' and
            # the raw OCR under 'screen_text'. The old code read 'text'/'analysis'/
            # 'ocr_text' — none of which exist — so it always returned "" and the
            # vision path looked broken. Read the real keys, preferring the AI
            # analysis over raw OCR.
            answer = r.get("answer") or r.get("ai_answer") or r.get("screen_text", "")
            return {
                "ok":          bool(r.get("success", r.get("ok", False))),
                "analysis":    r.get("answer") or r.get("ai_answer") or "",
                "screen_text": answer,
                "raw_text":    r.get("screen_text", ""),
                "method":      r.get("method", "unknown"),
                "error":       r.get("error"),
                "elements":    [],
            }
        except Exception as e:
            return {"ok": False, "screen_text": "", "analysis": "", "method": "none",
                    "error": str(e), "elements": []}

    # ── Stage 2: structured browser perception (DOM + bbox + clickable) ─────────
    def observe_browser(self, headless: bool = True) -> dict:
        """
        Extract structured elements from the live Playwright page.
        Returns {ok, method, url, elements:[{id,role,tag,text,bbox,clickable,...}], error}.
        bbox is [x, y, width, height] in CSS pixels relative to the viewport.
        """
        try:
            from agents.browser_agent import _get_context, _new_loop
            import asyncio

            async def _extract():
                ctx = await _get_context(headless)
                pages = ctx.pages
                page = pages[0] if pages else await ctx.new_page()
                url = page.url
                elements = await page.evaluate(_DOM_EXTRACT_JS)
                return url, elements

            loop = _new_loop()
            asyncio.set_event_loop(loop)
            url, elements = loop.run_until_complete(_extract())
            return {"ok": True, "method": "playwright_dom", "url": url,
                    "elements": elements, "error": None}
        except Exception as e:
            return {"ok": False, "method": "playwright_dom", "url": "",
                    "elements": [], "error": str(e)}

    # ── Stage 2: desktop OCR WITH bounding boxes ────────────────────────────────
    def observe_desktop(self) -> dict:
        """
        Screenshot + OCR with per-word bounding boxes (pytesseract.image_to_data).
        Returns {ok, method, elements:[{text, bbox, clickable=False}], error}.
        Unlike Stage 1 this gives COORDINATES, so desktop targets are actionable.
        """
        try:
            from agents import desktop_agent as da
            shot = da.screenshot()
            path = shot.get("path")
            if not path:
                return {"ok": False, "method": "ocr_boxes", "elements": [],
                        "error": "no screenshot path"}
            import pytesseract
            from PIL import Image
            img = Image.open(path)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            elements = []
            n = len(data["text"])
            for i in range(n):
                txt = (data["text"][i] or "").strip()
                if not txt:
                    continue
                if int(data.get("conf", [0]*n)[i] or 0) < 40:
                    continue
                elements.append({
                    "id": i, "role": "text", "text": txt,
                    "bbox": [data["left"][i], data["top"][i],
                             data["width"][i], data["height"][i]],
                    "clickable": False,
                })
            return {"ok": True, "method": "ocr_boxes", "elements": elements, "error": None}
        except Exception as e:
            return {"ok": False, "method": "ocr_boxes", "elements": [], "error": str(e)}

    # ── Element lookup for the Executor ─────────────────────────────────────────
    def find_element(self, elements: list, text: str = "", role: str = "",
                     clickable_only: bool = False) -> dict | None:
        """
        Find the best-matching element by (case-insensitive) text and/or role.
        Returns the element dict (with bbox + a click point) or None.
        """
        text_l = text.lower().strip()
        best = None
        for el in elements or []:
            if clickable_only and not el.get("clickable"):
                continue
            if role and el.get("role") != role:
                continue
            et = (el.get("text") or "").lower()
            if text_l:
                if text_l == et:
                    best = el; break               # exact match wins
                if text_l in et and best is None:
                    best = el                       # substring fallback
            elif not text_l:
                best = el; break
        if best:
            x, y, w, h = best["bbox"]
            best = {**best, "click_point": [x + w // 2, y + h // 2]}
        return best


perception = PerceptionAgent()
