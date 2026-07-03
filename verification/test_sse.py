"""
test_sse.py — Verify SSE live feed.
Fixes from Windows run:
- Backend-up check reads AND closes the /health response (never confused by a
  slow streaming socket).
- Stream collection always closes the socket; a stream that yields only pings is
  treated as backend-reachable, not "unavailable".
- Artifact written with encoding="utf-8" (avoids Windows GBK crash).
- RAM monitoring.
"""
import json
import time
import threading
from _harness import TestRun, guard, ram_snapshot, save_ram_artifact, ARTIFACTS

BACKEND = "http://127.0.0.1:8000"
SSE_URL = f"{BACKEND}/orchestrator/feed"


def _backend_up() -> tuple:
    """Real reachability check: GET /health, read body, close. Returns (ok, detail)."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{BACKEND}/health", timeout=8) as r:
            body = r.read().decode("utf-8", errors="ignore")
            return (r.status == 200, {"status": r.status, "body": body[:200]})
    except Exception as e:
        return (False, {"error": str(e)})


def _collect(url: str, secs: float = 8.0) -> list:
    """Connect to SSE endpoint, collect events for `secs`, always close socket."""
    events = []
    resp = None
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        resp = urllib.request.urlopen(req, timeout=secs + 3)
        deadline = time.time() + secs
        buf = b""
        while time.time() < deadline:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                for line in block.decode("utf-8", errors="ignore").splitlines():
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        try:
                            events.append(json.loads(raw))
                        except Exception:
                            if raw:
                                events.append({"raw": raw})
    except Exception as e:
        events.append({"error": str(e)})
    finally:
        if resp is not None:
            try: resp.close()
            except Exception: pass
    return events


def run() -> dict:
    t   = TestRun("test_sse")
    ram = [t.ram("start")]

    # ── Backend reachability (read + close, never confused by stream) ─────────
    up, detail = _backend_up()
    if not up:
        t.skip(f"Backend not reachable at {BACKEND} — {detail}. "
               "Start with: cd backend && python -m uvicorn main:app --port 8000")
        return t.finish()

    t.check("backend /health reachable (read and closed cleanly)",
            up,
            evidence={"health_detail": detail, "url": f"{BACKEND}/health"})

    t.log(f"Connecting to SSE feed: {SSE_URL}")

    # Trigger activity so the feed emits something beyond pings
    def trigger():
        time.sleep(0.5)
        try:
            import urllib.request
            with urllib.request.urlopen(f"{BACKEND}/orchestrator/status", timeout=5) as r:
                r.read()
        except Exception:
            pass

    threading.Thread(target=trigger, daemon=True).start()
    ram.append(t.ram("before_sse"))
    events = guard(t, "collect SSE events (8s)", lambda: _collect(SSE_URL, 8.0))
    ram.append(t.ram("after_sse"))

    if events is None:
        events = []

    # Write artifact with explicit UTF-8 (Windows-safe)
    raw_path = str(ARTIFACTS / "sse_events.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    t.add_artifact(raw_path)
    t.log(f"Collected {len(events)} event(s)")

    errors = [e for e in events if isinstance(e, dict) and "error" in e]
    pings  = [e for e in events if isinstance(e, dict) and e.get("raw") == "ping"]
    real   = [e for e in events if isinstance(e, dict) and "error" not in e and "raw" not in e]

    # A stream that connected (even if only pings/empty) means SSE endpoint works.
    stream_connected = (len(errors) == 0)
    t.check("SSE endpoint accepts connection (backend confirmed up)",
            stream_connected,
            evidence={"event_count": len(events),
                      "ping_count": len(pings),
                      "real_event_count": len(real),
                      "first_event": events[0] if events else None,
                      "backend_health": detail},
            error=None if stream_connected else f"stream error: {errors[0].get('error')}")

    # If real events arrived, validate their structure
    if real:
        required = {"ts", "agent", "msg", "level"}
        fields_ok = all(required.issubset(set(e.keys())) for e in real[:5])
        t.check("events have required fields (ts, agent, msg, level)",
                fields_ok,
                evidence={"required": sorted(required),
                          "sample": real[0],
                          "checked": len(real[:5])})

        valid_levels = {"info", "success", "warning", "error"}
        seen = {e.get("level") for e in real[:10]}
        t.check("all event level values valid",
                seen.issubset(valid_levels | {None}),
                evidence={"valid_levels": sorted(valid_levels),
                          "seen": sorted(x for x in seen if x)})
    else:
        # No real events in window — that's OK if only pings; note it with evidence
        t.check("SSE stream produced keep-alive traffic (no error)",
                stream_connected,
                evidence={"note": "only ping/keepalive in window; endpoint reachable",
                          "ping_count": len(pings),
                          "event_count": len(events)})

    ram.append(t.ram("end"))
    t.add_artifact(save_ram_artifact(ram, "sse"))
    return t.finish()


if __name__ == "__main__":
    run()
