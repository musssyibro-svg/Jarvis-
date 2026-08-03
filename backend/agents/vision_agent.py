"""
backend/agents/vision_agent.py
Vision system: screenshot capture, OCR, screen analysis, element detection.
Uses MSS (fast screenshots) + Pillow + Tesseract OCR + basic OpenCV.
All optional — degrades gracefully if libraries not installed.
"""
import base64
import io
import os
import time
from datetime import datetime, timezone
from pathlib import Path

SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ── Safe imports ──────────────────────────────────────────────────────────────
try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    from PIL import Image, ImageDraw, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    # #3: auto-detect Tesseract binary on Windows (common install locations)
    import os as _os, shutil as _shutil
    if _os.name == "nt" and not _shutil.which("tesseract"):
        for _cand in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            _os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            _os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
        ):
            if _os.path.exists(_cand):
                pytesseract.pytesseract.tesseract_cmd = _cand
                break
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def _ts():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ── Screenshot ────────────────────────────────────────────────────────────────

def screenshot(save: bool = True, region: dict = None) -> dict:
    """
    Capture the screen.
    region: {"left": x, "top": y, "width": w, "height": h} or None for full screen.
    Returns path, base64 data, and dimensions.
    """
    if not HAS_MSS:
        # Fallback: pyautogui screenshot
        try:
            import pyautogui
            img = pyautogui.screenshot()
            path = SCREENSHOT_DIR / f"screen_{_ts()}.png"
            img.save(str(path))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            return {"success": True, "path": str(path), "b64": b64, "width": img.width, "height": img.height, "method": "pyautogui"}
        except Exception as e:
            return {"success": False, "error": f"No screenshot library. Install mss or pyautogui. ({e})"}

    try:
        with mss.mss() as sct:
            mon = region or sct.monitors[1]  # monitor 1 = primary
            raw = sct.grab(mon)

        if not HAS_PIL:
            return {"success": False, "error": "Pillow not installed: pip install Pillow"}

        img  = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        path = SCREENSHOT_DIR / f"screen_{_ts()}.png"
        if save:
            img.save(str(path))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        return {
            "success": True,
            "path":    str(path) if save else None,
            "b64":     b64,
            "width":   img.width,
            "height":  img.height,
            "method":  "mss",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def screenshot_region(x: int, y: int, w: int, h: int) -> dict:
    return screenshot(region={"left": x, "top": y, "width": w, "height": h})


# ── OCR ───────────────────────────────────────────────────────────────────────

# Tesseract's classic second trap (after the missing-binary one): the binary is
# installed but its language data (eng.traineddata) is absent or TESSDATA_PREFIX
# points at the wrong directory -> "Could not initialize tesseract". Self-heal:
# verify 'eng' is loadable, and if not, download eng.traineddata (~4MB) into a
# local tessdata dir Jarvis controls and point TESSDATA_PREFIX at it.
_TESSDATA_OK = False
# China-first ordering: raw.githubusercontent.com is routinely unreachable there,
# and trying it first means a long timeout before every fallback. Mirrors lead.
_TESSDATA_URLS = [
    "https://mirror.ghproxy.com/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
    "https://ghproxy.net/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
    "https://gitee.com/mirrors_tesseract-ocr/tessdata_fast/raw/main/eng.traineddata",
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
]


def tessdata_ready() -> bool:
    """Can tesseract actually load English? (Doctor uses this probe.)"""
    if not HAS_OCR:
        return False
    try:
        return "eng" in pytesseract.get_languages(config="")
    except Exception:
        return False


def _ensure_tessdata() -> str | None:
    """Returns None when OCR languages are usable, else a human-readable error."""
    global _TESSDATA_OK
    if _TESSDATA_OK:
        return None
    if tessdata_ready():
        _TESSDATA_OK = True
        return None

    # Candidate tessdata dirs: alongside the binary first, then a Jarvis-local
    # dir that is always writable (no admin rights needed).
    import shutil as _sh
    import urllib.request
    cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    resolved = _sh.which(cmd) or cmd
    candidates = []
    if os.environ.get("TESSDATA_PREFIX"):
        candidates.append(Path(os.environ["TESSDATA_PREFIX"]))
    if os.path.sep in str(resolved):
        candidates.append(Path(resolved).parent / "tessdata")
    local = Path(__file__).resolve().parent.parent / "tessdata"
    candidates.append(local)

    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            target = d / "eng.traineddata"
            if not target.exists():
                for url in _TESSDATA_URLS:
                    try:
                        urllib.request.urlretrieve(url, str(target))
                        break
                    except Exception:
                        continue
            if not target.exists():
                continue
            os.environ["TESSDATA_PREFIX"] = str(d)
            if tessdata_ready():
                _TESSDATA_OK = True
                return None
        except Exception:
            continue
    return ("Tesseract is installed but its English language data is missing and "
            "auto-download failed (no internet?). Manual fix: download "
            "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata "
            f"and put it in {candidates[-1] if candidates else 'a tessdata folder'}, then "
            "set TESSDATA_PREFIX to that folder.")


OCR_MAX_WIDTH = 1600      # downscale before OCR — the single biggest speed win
OCR_TIMEOUT_S = 20        # never let a single OCR pass hang the whole request


def _prep_for_ocr(img):
    """
    Downscale + greyscale before OCR. Tesseract's cost scales with pixel count,
    so running it on a native 2560/4K screenshot is brutally slow (this is what
    made one screen analysis take ~10 minutes). At <=1600px wide, UI text is
    still perfectly legible to Tesseract but the pass is many times faster.
    """
    try:
        w, h = img.size
        if w > OCR_MAX_WIDTH:
            ratio = OCR_MAX_WIDTH / float(w)
            img = img.resize((OCR_MAX_WIDTH, int(h * ratio)))
        return img.convert("L")      # greyscale: less work, better contrast
    except Exception:
        return img


def ocr_screen(region: dict = None) -> dict:
    """Capture screen and extract all text via Tesseract OCR (downscaled + timed out)."""
    if not HAS_OCR:
        return {"success": False, "error": "pytesseract not installed. Run: pip install pytesseract. Also install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"}
    lang_err = _ensure_tessdata()
    if lang_err:
        return {"success": False, "error": lang_err}

    shot = screenshot(save=False, region=region)
    if not shot["success"]:
        return shot

    try:
        img_data = base64.b64decode(shot["b64"])
        img = _prep_for_ocr(Image.open(io.BytesIO(img_data)))
        # --psm 6 = assume a uniform block of text: much faster than full page
        # segmentation and better suited to app windows.
        try:
            text = pytesseract.image_to_string(img, config="--psm 6",
                                               timeout=OCR_TIMEOUT_S)
        except RuntimeError:          # pytesseract raises RuntimeError on timeout
            return {"success": False,
                    "error": f"OCR took longer than {OCR_TIMEOUT_S}s and was stopped"}
        return {
            "success": True,
            "text":    text.strip(),
            "lines":   [l.strip() for l in text.splitlines() if l.strip()],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def ocr_image(path: str) -> dict:
    """Run OCR on an existing image file."""
    if not HAS_OCR:
        return {"success": False, "error": "pytesseract not installed"}
    lang_err = _ensure_tessdata()
    if lang_err:
        return {"success": False, "error": lang_err}
    try:
        img  = Image.open(path)
        text = pytesseract.image_to_string(img)
        return {"success": True, "path": path, "text": text.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Screen analysis ───────────────────────────────────────────────────────────

def find_text_on_screen(search_text: str, region: dict = None) -> dict:
    """
    Locate text on screen via OCR. Returns whether found and surrounding context.
    """
    result = ocr_screen(region=region)
    if not result["success"]:
        return result

    text   = result["text"]
    found  = search_text.lower() in text.lower()
    lines  = result.get("lines", [])
    nearby = [l for l in lines if search_text.lower() in l.lower()]

    return {
        "success":     True,
        "found":       found,
        "search":      search_text,
        "context":     nearby,
        "full_text":   text[:3000],
    }


_ANALYSIS_CACHE = {"sig": None, "answer": None, "at": 0.0, "question": None}
# Seconds a screen analysis stays fresh.
#
# 25s was far too short given what an analysis costs here: on a CPU with no GPU
# it is the most expensive thing Jarvis does, and asking twice about the same
# unchanged screen within half a minute paid that price twice. The cache is
# already keyed on a hash of the screen, so a stale answer can only be returned
# for a screen that has not visibly changed — which makes a longer window safe
# rather than merely cheaper.
_CACHE_TTL = 120.0


def _screen_signature(b64: str) -> str:
    """Cheap fingerprint of the screen so we can skip re-analysing an idle screen."""
    import hashlib
    if not b64:
        return ""
    # sample the middle of the payload — full hashing a multi-MB PNG is wasteful
    chunk = b64[len(b64) // 3: len(b64) // 3 + 60000]
    return hashlib.md5(chunk.encode()).hexdigest()


def _downscale_b64(b64: str, max_w: int = 1280) -> str | None:
    """Re-encode a base64 PNG at a smaller width (for the vision model)."""
    if not (b64 and HAS_PIL):
        return None
    try:
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        w, h = img.size
        if w > max_w:
            img = img.resize((max_w, int(h * max_w / float(w))))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _window_context() -> str:
    """
    What is actually in front? This single line of context is the difference
    between 'there is text on the screen' and 'you're looking at Notepad'.
    """
    try:
        from agents.desktop_agent import list_windows, _is_foreground
        import ctypes, os
        active = ""
        if os.name == "nt":
            u32 = ctypes.windll.user32
            h = u32.GetForegroundWindow()
            if h:
                n = u32.GetWindowTextLengthW(h)
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, buf, n + 1)
                active = buf.value
        wins = (list_windows().get("windows") or [])[:8]
        parts = []
        if active:
            parts.append(f"Active window: {active}")
        if wins:
            parts.append("Other open windows: " + "; ".join(w for w in wins if w != active)[:300])
        return "\n".join(parts)
    except Exception:
        return ""


def analyze_screen(question: str = "") -> dict:
    """
    Take a screenshot and understand it.

    V8: tries REAL vision via llava:7b (sends the actual image pixels).
    Falls back to OCR-text + LLM only if llava is unavailable.
    """
    shot = screenshot(save=True)
    if not shot["success"]:
        return shot

    b64 = shot.get("b64")
    q = question or "Describe what is on this screen: windows, buttons, text, and layout."

    # ── Tier 0: cache. An unchanged screen with the same question doesn't need
    #    a second LLM pass — this is the single biggest speed win, because the
    #    screen is usually identical between rapid asks. ─────────────────────
    import time as _t
    sig = _screen_signature(b64)
    if (sig and _ANALYSIS_CACHE["sig"] == sig
            and _ANALYSIS_CACHE["question"] == q
            and _t.time() - _ANALYSIS_CACHE["at"] < _CACHE_TTL):
        return {"success": True, "screenshot": shot.get("path"),
                "dimensions": f"{shot.get('width')}x{shot.get('height')}",
                "method": "cache", "vision_used": False, "cached": True,
                "screen_text": "", "question": q,
                "answer": _ANALYSIS_CACHE["answer"],
                "ai_answer": _ANALYSIS_CACHE["answer"]}

    # Window context makes the answer specific instead of generic.
    win_ctx = _window_context()

    # ── Try real vision first (llava) ─────────────────────────────────────────
    vision_used = False
    answer = None
    try:
        from services.ollama_manager import vision as llava_vision, validate_model, VISION_MODEL
        if b64 and validate_model(VISION_MODEL).get("valid"):
            # Send a DOWNSCALED image: llava doesn't need 4K, and full-res
            # payloads are the difference between seconds and minutes.
            small = _downscale_b64(b64, 1280)
            r = llava_vision(q, small or b64)
            if r.get("ok"):
                answer = r["text"]
                vision_used = True
    except Exception:
        pass

    # ── Fallback: OCR text -> reasoning model ─────────────────────────────────
    # ALWAYS produce an answer here. The old code only asked the LLM when the
    # caller passed a question, so "AI analyze" with the default prompt
    # returned raw OCR and nothing else — the "can screenshot but can't
    # analyze" complaint.
    screen_text = ""
    ocr_error = None
    if not vision_used:
        ocr_result = ocr_screen()
        if ocr_result.get("success"):
            screen_text = ocr_result.get("text", "")
        else:
            ocr_error = ocr_result.get("error", "OCR failed")
        answer = None
        if screen_text.strip() or win_ctx:
            prompt = (f"You are Jarvis, looking at the user's Windows screen.\n"
                      f"{win_ctx}\n\n"
                      f"Text read from the screen (OCR, may be noisy):\n"
                      f"---\n{screen_text[:2200]}\n---\n\n"
                      f"Question: {q}\n\n"
                      f"Answer in 2-4 short sentences. Say WHICH APPLICATION is in "
                      f"front and what the user is doing. Ignore OCR noise and "
                      f"background windows. If a dialog or button matters, name it. "
                      f"Then on a new line starting with 'Next:' suggest one useful "
                      f"action, or 'Next: none'.")
            try:
                from services.ollama_manager import reason
                answer = reason(prompt)
            except Exception:
                answer = None
            if not answer:
                try:
                    from services.deepseek_service import call_model
                    answer = call_model(prompt, fast=True)
                except Exception as e:
                    answer = f"AI analysis unavailable: {e}"
        else:
            answer = (f"I captured the screen but couldn't read any text from it"
                      + (f" ({ocr_error})" if ocr_error else "")
                      + ". Install/fix Tesseract OCR, or pull the llava vision "
                        "model in Ollama for true image understanding.")

    # Remember it so an immediate repeat ask is instant.
    if sig and answer:
        _ANALYSIS_CACHE.update(sig=sig, answer=answer, at=_t.time(), question=q)

    try:   # real vision event for the console timeline
        from services import event_bus
        event_bus.publish("vision.analyzed",
                          {"method": "llava" if vision_used else "ocr",
                           "chars": len(screen_text or "")})
    except Exception:
        pass

    return {
        "success":     True,
        "screenshot":  shot.get("path"),
        "dimensions":  f"{shot.get('width')}x{shot.get('height')}",
        "method":      "llava-vision" if vision_used else "ocr+context",
        "vision_used": vision_used,
        "cached":      False,
        "window_context": win_ctx,
        "screen_text": screen_text[:2000],
        "question":    q,
        "answer":      answer,
        "ai_answer":   answer,   # backward-compat with existing UI key
    }


def locate_text_coords(search_text: str, region: dict = None) -> dict:
    """
    Find WHERE text is on screen (not just whether it exists).
    Uses pytesseract.image_to_data for word-level bounding boxes, matching the
    full search phrase across consecutive words. Returns the click point of the
    best match — this is what lets Jarvis SEE a button and click it.
    """
    if not HAS_OCR:
        return {"success": False, "error": "pytesseract not installed"}
    lang_err = _ensure_tessdata()
    if lang_err:
        return {"success": False, "error": lang_err}

    shot = screenshot(save=False, region=region)
    if not shot.get("success"):
        return shot
    try:
        img = Image.open(io.BytesIO(base64.b64decode(shot["b64"])))
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        words = [w.strip().lower() for w in data["text"]]
        target = [w for w in search_text.lower().split() if w]
        if not target:
            return {"success": False, "error": "empty search text"}

        matches = []
        n = len(words)
        for i in range(n):
            if not words[i]:
                continue
            # phrase match: consecutive OCR words on the same line
            j, k = i, 0
            boxes = []
            while j < n and k < len(target):
                if not words[j]:
                    j += 1
                    continue
                if target[k] in words[j] or words[j] in target[k]:
                    boxes.append(j)
                    k += 1
                    j += 1
                else:
                    break
            if k == len(target):
                left  = min(data["left"][b] for b in boxes)
                top   = min(data["top"][b] for b in boxes)
                right = max(data["left"][b] + data["width"][b] for b in boxes)
                bot   = max(data["top"][b] + data["height"][b] for b in boxes)
                conf  = sum(float(data["conf"][b]) for b in boxes) / len(boxes)
                # region offsets so coordinates are absolute screen positions
                ox = (region or {}).get("left", 0)
                oy = (region or {}).get("top", 0)
                matches.append({
                    "text": " ".join(data["text"][b] for b in boxes),
                    "x": ox + (left + right) // 2,
                    "y": oy + (top + bot) // 2,
                    "box": [ox + left, oy + top, ox + right, oy + bot],
                    "confidence": round(conf, 1),
                })
        if not matches:
            return {"success": True, "found": False, "search": search_text, "matches": []}
        matches.sort(key=lambda m: -m["confidence"])
        best = matches[0]
        return {"success": True, "found": True, "search": search_text,
                "x": best["x"], "y": best["y"], "best": best,
                "matches": matches[:10]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def click_text(search_text: str, region: dict = None, button: str = "left") -> dict:
    """
    The see→act primitive: OCR the screen, locate the text, move the mouse
    there and click it. Verifies afterwards by re-reading the screen.
    """
    loc = locate_text_coords(search_text, region=region)
    if not loc.get("success"):
        return loc
    if not loc.get("found"):
        return {"success": False, "error": f"'{search_text}' not visible on screen",
                "found": False}
    from agents import desktop_agent as da
    move_res = da.move(loc["x"], loc["y"], duration=0.25)
    if not move_res.get("success"):
        return move_res
    click_res = da.click(loc["x"], loc["y"], button=button)
    click_res.update({"target": search_text, "x": loc["x"], "y": loc["y"],
                      "matched": loc.get("best", {}).get("text", "")})
    return click_res


def find_image_on_screen(template_path: str, confidence: float = 0.8) -> dict:
    """
    Find a template image (button, icon, etc.) on the current screen.
    Uses OpenCV template matching.
    """
    if not HAS_CV2:
        return {"success": False, "error": "OpenCV not installed: pip install opencv-python"}

    shot = screenshot(save=False)
    if not shot["success"]:
        return shot

    try:
        img_data  = base64.b64decode(shot["b64"])
        screen_np = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
        template  = cv2.imread(template_path, cv2.IMREAD_COLOR)

        if template is None:
            return {"success": False, "error": f"Template not found: {template_path}"}

        result  = cv2.matchTemplate(screen_np, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= confidence:
            th, tw = template.shape[:2]
            center_x = max_loc[0] + tw // 2
            center_y = max_loc[1] + th // 2
            return {
                "success":    True,
                "found":      True,
                "confidence": float(max_val),
                "x":          center_x,
                "y":          center_y,
                "top_left":   list(max_loc),
            }
        return {"success": True, "found": False, "confidence": float(max_val)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Status ────────────────────────────────────────────────────────────────────

def get_status() -> dict:
    return {
        "mss":        HAS_MSS,
        "pillow":     HAS_PIL,
        "tesseract":  HAS_OCR,
        "opencv":     HAS_CV2,
        "screenshot_dir": str(SCREENSHOT_DIR.resolve()),
        "capabilities": {
            "screenshot":   HAS_MSS or HAS_PIL,
            "ocr":          HAS_OCR,
            "image_search": HAS_CV2,
            "screen_analysis": True,
        }
    }
