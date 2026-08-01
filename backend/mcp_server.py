"""
mcp_server.py — drive Jarvis from any MCP client.

Jarvis stays the brain. This is a second door into it, so Claude Desktop, Cherry
Studio, Cline, Chatbox or Open WebUI can ask Jarvis to do things without any of
them replacing it. The React console remains the primary interface; these are
additional, disposable, swappable clients. Nothing about Jarvis changes.

TWO DELIBERATE CHOICES, both against the obvious approach:

1. HAND-WRITTEN TOOLS, NOT AUTO-CONVERTED ROUTES. FastMCP will happily turn all
   ~123 FastAPI routes into tools in one line. FastMCP's own documentation warns
   against shipping that: models perform markedly better against a small curated
   surface than a mirrored API. So there are fourteen tools here, each named for
   an intention ("search_the_web") rather than a mechanism ("post_agents_desktop"),
   and each one wraps whatever number of internal calls it takes.

2. NO LOW-LEVEL PRIMITIVES. There is no click_mouse or press_key. If those were
   exposed, every client would build its own fragile ad-hoc automation on top,
   and swapping Playwright or the OCR engine later would break all of them. High
   level tools mean the internals stay free to change.

SECURITY. This is the lethal trifecta in one process: private data (a browser
logged into your freelance accounts), untrusted content (every job description
it scrapes), and outbound communication. So:

  * loopback only, always — never bind this to 0.0.0.0
  * anything that submits, types, or runs a command is NOT auto-approved; it
    goes through the same approval queue the UI uses
  * scraped text reaching a model is data, never instruction

Run it:  python backend/mcp_server.py            (stdio, for Claude Desktop)
         python backend/mcp_server.py --http     (127.0.0.1:8765, multi-client)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    from fastmcp import FastMCP
except ImportError:                                   # pragma: no cover
    print("This needs FastMCP:\n"
          "    pip install fastmcp\n"
          "Jarvis itself runs fine without it — this is only the extra door "
          "that lets other AI apps drive Jarvis.", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP(
    "jarvis",
    instructions=(
        "Jarvis is a local assistant running on the user's own Windows PC. It can "
        "control the desktop, drive a browser that is already signed in to the "
        "user's freelance accounts, and run an autonomous income engine.\n\n"
        "Prefer run_task for anything phrased as an instruction — it decomposes "
        "multi-step commands properly. Use the specific tools when you know "
        "exactly what you want.\n\n"
        "Anything that types, submits or runs a command needs the user's approval "
        "and will come back as 'awaiting approval'. That is not an error; do not "
        "retry it or look for a way around it."
    ),
)


def _j(fn, *a, **kw) -> dict:
    """Call into Jarvis, returning an error object rather than raising at a client."""
    try:
        return fn(*a, **kw) or {}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ── understanding ────────────────────────────────────────────────────────────

@mcp.tool
def whats_on_this_machine() -> dict:
    """
    What the user's PC actually has: browsers, apps, RAM, GPU, language, network,
    installed AI models — and the constraints those impose.

    Read this before suggesting anything the machine may not support. It is the
    difference between recommending Chrome and noticing there isn't one.
    """
    from services import environment
    return _j(environment.scan)


@mcp.tool
def what_do_you_know_about_me() -> dict:
    """
    The durable facts Jarvis holds about its user — location, preferred apps,
    writing style, constraints — plus where each fact came from.
    """
    from services import persona
    return _j(persona.status)


@mcp.tool
def remember_about_me(field: str, value: str) -> dict:
    """
    Record a durable fact about the user so it stops being re-asked.

    Valid fields: name, location, languages, browser, search_engine,
    messaging_app, editor, writing_style, work_hours, occupation, interests,
    favourite_sites, constraints, dislikes.
    """
    from services import persona
    return _j(persona.remember, field, value, persona.STATED, "set over MCP")


# ── doing ────────────────────────────────────────────────────────────────────

@mcp.tool
def preview_task(command: str) -> dict:
    """
    Show the plan for a command WITHOUT running it.

    Worth calling first for anything ambiguous: it reveals how the sentence was
    split, which is where misunderstandings actually happen.
    """
    from services import decompose
    return _j(decompose.preview, command)


@mcp.tool
def simulate(command: str = "") -> dict:
    """
    Show what WOULD happen, without doing any of it.

    Call this before run_task for anything the user might not want done blindly,
    and always before find_freelance_jobs — that one can send proposals to real
    clients under the user's name.

    Pass a command for a task simulation, or nothing for a freelance cycle.
    Returns every step, what each one touches, a time estimate and any blockers.
    Executes nothing.
    """
    from services import simulate as sim
    return _j(sim.task, command) if command.strip() else _j(sim.earning)


@mcp.tool
def run_task(command: str) -> dict:
    """
    Do something on the user's PC, described in plain language.

    Handles multi-step instructions ("open the browser, search BMW M4, and tell
    me what it says"). Returns what ran, which steps verified, and — if it broke
    — where and why, never a bare failure.

    Steps that type or run commands require the user's approval; those come back
    marked awaiting approval rather than silently skipped.
    """
    from adapters.commander_adapter import handle_chat
    return _j(handle_chat, command, "mcp")


@mcp.tool
def search_the_web(query: str, then_summarise: bool = True) -> dict:
    """
    Search and, by default, read the results back.

    Uses whichever browser the machine actually has and whichever search engine
    reaches from the user's network — Google is unreachable where this user is.
    """
    cmd = f"open browser and search {query}"
    if then_summarise:
        cmd += " and analyze the page"
    from adapters.commander_adapter import handle_chat
    return _j(handle_chat, cmd, "mcp")


@mcp.tool
def look_at_the_screen(question: str = "") -> dict:
    """
    Screenshot the user's screen and answer a question about it.

    Slow on this machine — there's no usable GPU, so vision runs on the CPU.
    Expect tens of seconds, and ask one specific question rather than several.
    """
    from adapters.commander_adapter import handle_chat
    return _j(handle_chat, question or "what's on my screen", "mcp")


@mcp.tool
def control_desktop(instruction: str) -> dict:
    """
    Open apps, type, click, press keys — described in plain language.

    Same engine as run_task, with the intent fixed to desktop control. Every
    step is verified against the real screen: a step is only 'done' once the
    window or the typed text was actually observed.
    """
    from adapters.commander_adapter import handle_chat
    return _j(handle_chat, instruction, "mcp")


# ── the income engine ────────────────────────────────────────────────────────

@mcp.tool
def find_freelance_jobs() -> dict:
    """
    Run one scan-and-draft cycle across the user's freelance platforms: find
    jobs, score them against the profile, draft proposals for the good ones.

    Drafts only. Nothing is submitted without the user approving it — see
    review_proposals.
    """
    from services import income_engine
    return _j(income_engine.run_once_now)


@mcp.tool
def review_proposals(limit: int = 20) -> dict:
    """
    The proposals Jarvis has drafted and is holding for approval — full text,
    target job, and score. Nothing listed here has been sent.
    """
    from models.db import conn
    def _read():
        with conn() as db:
            rows = db.execute(
                "SELECT id, platform, job_title, action, status, payload, created_at "
                "FROM automation_queue WHERE status IN ('pending','approved') "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        import json
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except Exception:
                pass
            out.append(d)
        return {"proposals": out,
                "note": "Approve these in the Earn screen. Nothing here has been sent."}
    return _j(_read)


@mcp.tool
def earnings_report() -> dict:
    """How the income engine is doing: jobs found, proposals sent, replies, wins."""
    from services import analytics_service
    return _j(analytics_service.get_analytics)


@mcp.tool
def income_engine_status() -> dict:
    """Is the always-on freelance engine running, what has it done, and when next?"""
    from services import income_engine
    return _j(income_engine.status)


# ── watching itself ──────────────────────────────────────────────────────────

@mcp.tool
def current_plan() -> dict:
    """The plan Jarvis is executing right now, step by step, with live status."""
    from services import live_plan
    return _j(live_plan.snapshot)


@mcp.tool
def why_did_that_happen() -> dict:
    """
    The chain behind the last outcome: every step, how long it took, exactly
    where it broke, the cause, the fix, and the machine fact behind it.

    Assembled from recorded observations — this is not a model narrating its own
    behaviour, so it can be trusted when it disagrees with the summary.
    """
    from services import narrate
    return _j(narrate.why)


@mcp.tool
def stop_what_youre_doing(reason: str = "") -> dict:
    """
    Halt cleanly. The step in flight finishes first — stopping mid-keystroke
    leaves half a sentence in a document, and mid-submission leaves a half-filled
    form on a real freelance site.
    """
    from services import live_plan
    return _j(live_plan.stop, reason)


@mcp.tool
def teach_by_watching(action: str, name: str = "") -> dict:
    """
    Learn a task by watching the user do it once.

    action="start" begins recording (pass a name, e.g. "apply for a job"),
    action="stop" saves what was demonstrated as a replayable workflow.

    Passwords are never captured — a login step becomes a vault lookup instead.
    """
    from services import teach
    if action == "start":
        return _j(teach.start, name)
    if action == "stop":
        return _j(teach.stop)
    return {"error": "action must be 'start' or 'stop'", "status": _j(teach.status)}


# ── serving ──────────────────────────────────────────────────────────────────

def _http_auth():
    """
    A token gate for HTTP mode.

    stdio needs none: the client launches this process, owns it, and nothing is
    listening on a port. HTTP is different — an open port that can type on the
    user's keyboard and drive a logged-in browser is the exact shape of the
    problem Microsoft's AutoJack research described, where untrusted web content
    reached a local agent socket. Loopback is not a trust boundary on its own.

    Returns middleware, or None if this FastMCP build doesn't expose the hook —
    in which case we say so plainly rather than implying protection that isn't
    there.
    """
    from services import auth
    token = auth.token()

    try:
        from starlette.middleware import Middleware
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
    except ImportError:
        return None, token

    class _Gate(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            supplied = (request.headers.get("x-jarvis-token", "")
                        or request.headers.get("authorization", "")
                        .removeprefix("Bearer ").strip())
            if not auth.token_ok(supplied):
                return JSONResponse(
                    {"error": "This Jarvis MCP server needs a token. It's in "
                              "backend/.jarvis_token — send it as the "
                              "X-Jarvis-Token header, or as a Bearer token."},
                    status_code=401)
            return await call_next(request)

    return [Middleware(_Gate)], token


def main() -> None:
    http = "--http" in sys.argv
    if not http:
        # stdio: the client launches this process and owns it. Nothing is
        # listening on a port, which is the safest shape for a single client.
        mcp.run()
        return

    host = "127.0.0.1"      # not configurable on purpose — see the module docstring
    port = int(os.getenv("JARVIS_MCP_PORT", "8765"))
    middleware, token = _http_auth()

    print(f"\nJarvis MCP  ->  http://{host}:{port}/mcp   (loopback only)",
          file=sys.stderr)
    print("Point Cherry Studio / Claude Desktop / Cline at that URL.\n",
          file=sys.stderr)
    if middleware:
        print("This port requires a token. In your client, add the header:",
              file=sys.stderr)
        print(f"    X-Jarvis-Token: {token}\n", file=sys.stderr)
        print("(Also saved in backend/.jarvis_token. Don't paste it into a chat.)\n",
              file=sys.stderr)
    else:
        print("!! This FastMCP build doesn't expose a middleware hook, so the",
              file=sys.stderr)
        print("!! port is UNAUTHENTICATED. Any program on this PC can drive",
              file=sys.stderr)
        print("!! Jarvis. Use stdio mode instead unless you need multiple",
              file=sys.stderr)
        print("!! clients at once.\n", file=sys.stderr)

    try:
        mcp.run(transport="http", host=host, port=port, middleware=middleware)
    except TypeError:
        # Older FastMCP: no middleware parameter. Refuse rather than serve an
        # open door while having just printed that it's protected.
        if middleware:
            print("This FastMCP version can't take the auth middleware.",
                  file=sys.stderr)
            print("Upgrade it:   pip install -U fastmcp", file=sys.stderr)
            print("Or use stdio mode (no --http), which needs no token.",
                  file=sys.stderr)
            sys.exit(1)
        mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
