"""
test_llava.py — Verify vision pipeline (final).
- SKIP if neither Ollama package nor llava model available
- Known 50x50 red-square image; keyword check on response
- RAM snapshots before/during/after llava call
- OCR fallback path documented
"""
import base64
import json
import struct
import zlib

from _harness import ARTIFACTS, TestRun, dump_ollama_status, guard, ram_snapshot, save_ram_artifact


# ── Known test image: 50x50 solid red square (stdlib only) ────────────────────
def _make_red_png(size=50) -> bytes:
    def chunk(name, data):
        c = struct.pack(">I", len(data)) + name + data
        return c + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    raw  = b"".join(b"\x00" + b"\xFF\x00\x00" * size for _ in range(size))
    idat = chunk(b"IDAT", zlib.compress(raw))
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + chunk(b"IEND", b"")

RED_PNG      = _make_red_png()
RED_B64      = base64.b64encode(RED_PNG).decode()
KEYWORDS     = ["red", "square", "color", "colour", "image"]


def run() -> dict:
    t   = TestRun("test_llava")
    ram = []
    ram.append(t.ram("start"))

    # Always dump Ollama status
    t.add_artifact(dump_ollama_status())

    # Save the test image so it appears in artifacts
    img_path = str(ARTIFACTS / "test_red_square.png")
    open(img_path, "wb").write(RED_PNG)
    t.add_artifact(img_path)
    t.log(f"Test image: 50×50 red square PNG ({len(RED_PNG)} bytes)")

    # Import ollama_manager
    om = guard(t, "import ollama_manager",
               lambda: __import__("services.ollama_manager",
                                  fromlist=["vision","validate_model",
                                            "VISION_MODEL","LARGE_MODELS","status"]))
    if om is None:
        return t.finish()

    t.check("vision model configured as llava:7b",
            om.VISION_MODEL == "llava:7b",
            evidence={"VISION_MODEL": om.VISION_MODEL})

    t.check("llava in LARGE_MODELS (lazy-load enforced)",
            om.VISION_MODEL in om.LARGE_MODELS,
            evidence={"LARGE_MODELS": sorted(om.LARGE_MODELS)})

    st = guard(t, "ollama_manager.status()", lambda: om.status())
    t.check("status() returns model config",
            isinstance(st, dict) and "models" in st,
            evidence={"models": (st or {}).get("models"),
                      "health_ok": (st or {}).get("health", {}).get("ok")})

    # Check Ollama daemon reachable at all
    h = guard(t, "ollama health()", lambda: om.health())
    if not (h and h.get("ok")):
        reason = (h or {}).get("reason", "ollama unreachable or not installed")
        t.skip(f"Ollama not reachable — {reason}. "
               "Start with: ollama serve && ollama pull llava:7b")
        t.add_artifact(save_ram_artifact(ram, "llava_skip"))
        return t.finish()

    # Check llava pulled
    v = guard(t, "validate llava model", lambda: om.validate_model(om.VISION_MODEL))
    llava_ok = bool(v and v.get("valid"))
    t.log(f"llava available: {llava_ok}  detail={v}")

    if llava_ok:
        t.log("llava present — running REAL vision call on known red-square image")
        ram.append(t.ram("before_llava_call"))

        r = guard(t, "vision() on red square",
                  lambda: om.vision(
                      "What color is this image? What shape do you see? "
                      "Describe the content in one sentence.",
                      RED_B64))

        ram.append(t.ram("after_llava_call"))

        t.check("vision() call succeeds",
                bool(r and r.get("ok")),
                evidence={"answer": (r or {}).get("text", "")[:300],
                          "error":  (r or {}).get("error")},
                error=None if (r and r.get("ok")) else (r or {}).get("error","unknown"))

        if r and r.get("ok"):
            answer = r.get("text", "").lower()
            found  = [kw for kw in KEYWORDS if kw in answer]
            t.check("response contains expected keywords (red/square/color/etc.)",
                    len(found) >= 2,
                    evidence={"response":        r.get("text","")[:250],
                              "keywords_found":  found,
                              "keywords_checked": KEYWORDS,
                              "ram_before":      ram[-2],
                              "ram_after":       ram[-1]},
                    error=None if len(found) >= 2
                          else f"only {found} matched in: {r.get('text','')[:80]}")
    else:
        # llava not pulled → verify safe refusal (no crash, no RAM spike)
        t.log("llava not pulled — verifying safe refusal path")
        ram.append(t.ram("before_refused_call"))
        r = guard(t, "vision() refuses cleanly",
                  lambda: om.vision("describe", RED_B64))
        ram.append(t.ram("after_refused_call"))

        t.check("vision() refuses safely when llava absent",
                bool(r and r.get("ok") is False and r.get("error")),
                evidence={"ok":    (r or {}).get("ok"),
                          "error": (r or {}).get("error","")[:120],
                          "ram_before": ram[-2],
                          "ram_after":  ram[-1]})

    # OCR fallback path: verify vision_agent reports method correctly
    va = guard(t, "import vision_agent",
               lambda: __import__("agents.vision_agent", fromlist=["get_status"]))
    if va:
        caps = va.get_status().get("capabilities", {})
        t.check("vision_agent capabilities dict non-empty",
                isinstance(caps, dict) and len(caps) > 0,
                evidence={"capabilities": caps})

    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "llava"))
    return t.finish()


if __name__ == "__main__":
    run()
