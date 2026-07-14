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
_TESSDATA_URLS = [
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
    # mirrors for networks where raw.githubusercontent.com is unreachable
    "https://mirror.ghproxy.com/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
    "https://ghproxy.net/https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata",
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


def ocr_screen(region: dict = None) -> dict:
    """Capture screen and extract all text via Tesseract OCR."""
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
        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img)
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

    # ── Try real vision first (llava) ─────────────────────────────────────────
    vision_used = False
    answer = None
    try:
        from services.ollama_manager import vision as llava_vision, validate_model, VISION_MODEL
        if b64 and validate_model(VISION_MODEL).get("valid"):
            r = llava_vision(q, b64)
            if r.get("ok"):
                answer = r["text"]
                vision_used = True
    except Exception:
        pass

    # ── Fallback: OCR text -> reasoning model ─────────────────────────────────
    screen_text = ""
    if not vision_used:
        ocr_result = ocr_screen()
        screen_text = ocr_result.get("text", "") if ocr_result.get("success") else ""
        if question:
            try:
                from services.ollama_manager import reason
                answer = reason(
                    f"Screen OCR text:\n{screen_text[:1500]}\n\nQuestion: {q}\nAnswer from the text above."
                )
            except Exception as e:
                answer = f"AI analysis unavailable: {e}"
        else:
            answer = None

    return {
        "success":     True,
        "screenshot":  shot.get("path"),
        "dimensions":  f"{shot.get('width')}x{shot.get('height')}",
        "method":      "llava-vision" if vision_used else "ocr-fallback",
        "vision_used": vision_used,
        "screen_text": screen_text[:2000],
        "question":    q,
        "answer":      answer,
        "ai_answer":   answer,   # backward-compat with existing UI key
    }


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
