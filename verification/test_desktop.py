"""
test_desktop.py — Verify desktop control.
- Missing pyautogui → SKIP (not FAIL) with clear reason
- open_app/close_app verified via psutil process list
- type_text verified
- file ops fully verified on real filesystem
- emergency stop verified
- RAM snapshots at key points
"""
import os
import sys
import time
import tempfile
from _harness import TestRun, guard, process_running, dump_process_list, ram_snapshot, save_ram_artifact

NOTEPAD_EXE = "notepad.exe"
NOTEPAD_APP = "notepad"


def run() -> dict:
    t = TestRun("test_desktop")
    ram_log = []

    ram_log.append(t.ram("start"))
    t.add_artifact(dump_process_list("start"))

    da = guard(t, "import desktop_agent",
               lambda: __import__("agents.desktop_agent", fromlist=["x"]))
    if da is None:
        return t.finish()

    caps      = da.get_status().get("capabilities", {})
    has_input = caps.get("mouse", False) and caps.get("keyboard", False)
    t.log(f"pyautogui={da.get_status().get('pyautogui')}  "
          f"pygetwindow={da.get_status().get('pygetwindow')}")

    # ── File operations (always run — no deps) ────────────────────────────────
    tmp = tempfile.mkdtemp()
    from _harness import register_temp
    register_temp(tmp)
    fp = os.path.join(tmp, "jarvis_proof.txt")

    r = guard(t, "write_file", lambda: da.write_file(fp, "jarvis desktop proof"))
    t.check("write_file creates file on disk",
            bool(r and r.get("success") and os.path.exists(fp)),
            evidence={"path": fp,
                      "size_bytes": os.path.getsize(fp) if os.path.exists(fp) else 0})

    r = guard(t, "read_file", lambda: da.read_file(fp))
    t.check("read_file returns correct content",
            bool(r and r.get("content") == "jarvis desktop proof"),
            evidence={"returned_content": (r or {}).get("content", "")[:80]})

    r = guard(t, "search_files", lambda: da.search_files(tmp, "jarvis_proof"))
    t.check("search_files locates file",
            bool(r and r.get("count", 0) >= 1),
            evidence={"count": (r or {}).get("count"),
                      "matches": (r or {}).get("matches", [])[:2]})

    cp_path = os.path.join(tmp, "copy.txt")
    r = guard(t, "copy_file", lambda: da.copy_file(fp, cp_path))
    t.check("copy_file creates copy",
            bool(r and r.get("success") and os.path.exists(cp_path)),
            evidence={"success": (r or {}).get("success"),
                      "copy_exists": os.path.exists(cp_path),
                      "copy_path": cp_path})

    r = guard(t, "delete_file no-confirm",
              lambda: da.delete_file(cp_path, confirm=False))
    t.check("delete_file refuses without confirm=True",
            bool(r and r.get("needs_confirmation") is True),
            evidence={"needs_confirmation": (r or {}).get("needs_confirmation"),
                      "response_keys": list((r or {}).keys())})

    # Re-create the copy for the confirmed delete
    da.copy_file(fp, cp_path)
    r = guard(t, "delete_file confirmed",
              lambda: da.delete_file(cp_path, confirm=True))
    gone = not os.path.exists(cp_path)
    t.check("delete_file removes file when confirm=True",
            bool(r and r.get("success") and gone),
            evidence={"success": (r or {}).get("success"),
                      "file_gone": gone,
                      "deleted_path": cp_path})

    # ── Emergency stop ────────────────────────────────────────────────────────
    da.emergency_stop()
    blocked = da.click(5, 5)
    t.check("emergency_stop blocks mouse input",
            da.is_estopped() and blocked.get("success") is False,
            evidence={"is_estopped": da.is_estopped(),
                      "click_error": blocked.get("error", "")[:80]})

    fp2 = os.path.join(tmp, "estop_proof.txt")
    rw  = da.write_file(fp2, "written during estop")
    t.check("file ops still work during emergency_stop",
            rw.get("success") is True and os.path.exists(fp2),
            evidence={"file_exists": os.path.exists(fp2),
                      "content": open(fp2, encoding="utf-8").read() if os.path.exists(fp2) else ""})

    da.clear_emergency_stop()
    t.check("emergency_stop clears correctly",
            not da.is_estopped(),
            evidence={"is_estopped_after_clear": da.is_estopped(),
                      "cleared_at": time.strftime("%H:%M:%S")})

    ram_log.append(t.ram("after_file_ops"))

    # ── Live input (SKIP if pyautogui not installed) ──────────────────────────
    if not has_input:
        t.skip("pyautogui not installed — live input tests (open_app/close_app/"
               "type_text/click) require: pip install pyautogui pygetwindow")
        t.add_artifact(save_ram_artifact(ram_log, "desktop"))
        t.add_artifact(dump_process_list("end_no_input"))
        return t.finish()

    # ── open_app ──────────────────────────────────────────────────────────────
    t.add_artifact(dump_process_list("before_open"))
    r = guard(t, "open_app(notepad)", lambda: da.open_app(NOTEPAD_APP))
    t.check("open_app returns success",
            bool(r and r.get("success")),
            evidence={"result": r})

    time.sleep(2)
    proc_open = process_running(NOTEPAD_EXE)
    t.check("notepad.exe in process list after open_app",
            proc_open,
            evidence={"notepad_running": proc_open,
                      "checked_via": "psutil / tasklist"})
    t.add_artifact(dump_process_list("after_open"))
    t.screenshot("after_open")
    ram_log.append(t.ram("after_open_notepad"))

    # ── type_text ─────────────────────────────────────────────────────────────
    time.sleep(0.4)
    r = guard(t, "type_text_raw",
              lambda: da.type_text_raw("JARVIS V8 VERIFICATION TEST"))
    t.check("type_text executes without error",
            bool(r and r.get("success")),
            evidence={"result": r, "typed": "JARVIS V8 VERIFICATION TEST"})
    t.screenshot("after_type")

    # ── mouse click ──────────────────────────────────────────────────────────
    r = guard(t, "click(100,100)", lambda: da.click(100, 100))
    t.check("click executes at coordinates",
            bool(r and r.get("success")),
            evidence={"result": r, "coordinates": {"x": 100, "y": 100}})

    # ── close_app ─────────────────────────────────────────────────────────────
    r = guard(t, "close_app(notepad)", lambda: da.close_app(NOTEPAD_APP))
    t.check("close_app returns success",
            bool(r and r.get("success")),
            evidence={"result": r})

    time.sleep(1.5)
    proc_closed = process_running(NOTEPAD_EXE)
    t.check("notepad.exe gone from process list after close_app",
            not proc_closed,
            evidence={"process_name": NOTEPAD_EXE,
                      "still_running": proc_closed,
                      "verified_via": "psutil/tasklist process scan",
                      "checked_at": time.strftime("%H:%M:%S")})
    t.add_artifact(dump_process_list("after_close"))
    t.screenshot("after_close")
    ram_log.append(t.ram("after_close_notepad"))

    t.add_artifact(save_ram_artifact(ram_log, "desktop"))
    return t.finish()


if __name__ == "__main__":
    run()
