"""
services/auth.py — the gate in front of a machine that can type on your keyboard.

Jarvis can open your apps, type into them, run shell commands, and drive a
browser that is already logged into your freelance accounts. That is a large
amount of authority to leave on an unauthenticated HTTP port.

The threat is not a hacker on your network. It is far more mundane: any web page
you visit can issue requests to http://127.0.0.1:8000. Browsers happily allow
that. Without a check, a page you opened in another tab could POST to
/agents/desktop and start typing. Microsoft's 2026 AutoJack write-up put it
plainly — localhost stopped being a trust boundary once agents began browsing
untrusted content next to privileged local control planes.

Three defences, cheapest first:

  1. ORIGIN / HOST CHECK — a browser always sends Origin on a cross-site request.
     Rejecting unknown Origins blocks drive-by pages and DNS rebinding, and
     costs a legitimate user nothing. This is on by default.

  2. TOKEN — a shared secret generated on first run and written to a file only
     this account can read. Required for anything that acts on the machine, and
     for everything once the server is not on loopback.

  3. DESKTOP CONTROL FLAG — keyboard, mouse and shell can be turned off entirely
     without turning off Jarvis, for when you want the freelance engine running
     but nothing touching your desktop.

The defaults are chosen so a normal local run needs no configuration. Security
that makes the thing annoying to start gets disabled, and then protects nothing.
"""
from __future__ import annotations

import ipaddress
import os
import secrets
import stat
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_FILE = BASE_DIR / ".jarvis_token"

# Paths that never need a token: liveness, the docs page, and the token handshake
# itself. Keep this list tiny and boring.
OPEN_PATHS = {"/", "/health", "/api/docs", "/openapi.json", "/api/redoc",
              "/auth/status"}
OPEN_PREFIXES = ("/static/",)

# Paths that act on the machine. These need the token even on loopback when a
# token is configured, and they are what DESKTOP_CONTROL_ENABLED switches off.
CONTROL_PREFIXES = ("/agents/desktop", "/agents/execute", "/agents/run",
                    "/os/control", "/os/teach", "/automation/queue",
                    "/v9/goal", "/orchestrator/start", "/workflows/run",
                    "/planner/run")

_cached_token: str | None = None


# ── token ────────────────────────────────────────────────────────────────────

def token() -> str:
    """
    The current token, generated and persisted on first use.

    Written with owner-only permissions. On Windows that chmod is close to a
    no-op, so the real protection there is that the file sits in the user's own
    profile — worth knowing rather than pretending otherwise.
    """
    global _cached_token
    if _cached_token:
        return _cached_token
    env = (os.getenv("JARVIS_TOKEN") or "").strip()
    if env:
        _cached_token = env
        return env
    try:
        if TOKEN_FILE.exists():
            saved = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if saved:
                _cached_token = saved
                return saved
    except Exception:
        pass
    fresh = secrets.token_urlsafe(24)
    try:
        TOKEN_FILE.write_text(fresh, encoding="utf-8")
        os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    _cached_token = fresh
    return fresh


def rotate() -> str:
    """New token. Every existing client must be given the new one."""
    global _cached_token
    _cached_token = None
    try:
        TOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    os.environ.pop("JARVIS_TOKEN", None)
    return token()


# ── settings ─────────────────────────────────────────────────────────────────

def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        try:
            from services import config
            v = config.get(name.lower(), "")
        except Exception:
            v = ""
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def require_token() -> bool:
    """
    Off by default on loopback, forced on when bound anywhere else.

    A local single-user run shouldn't need a header to work — but the moment the
    server is reachable from the network, "off by default" would be an unlocked
    door, so that case is not left to configuration.
    """
    if _flag("JARVIS_REQUIRE_TOKEN", False):
        return True
    host = os.getenv("JARVIS_HOST", "127.0.0.1")
    return not _is_loopback(host)


def desktop_control_enabled() -> bool:
    return _flag("DESKTOP_CONTROL_ENABLED", True)


def check_origin() -> bool:
    return _flag("JARVIS_CHECK_ORIGIN", True)


def _is_loopback(host: str) -> bool:
    h = (host or "").split(":")[0].strip("[]")
    if h in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


# ── the checks ───────────────────────────────────────────────────────────────

def origin_ok(origin: str, host_header: str) -> tuple[bool, str]:
    """
    Is this request coming from somewhere we recognise?

    No Origin at all is allowed: curl, the MCP server and every non-browser
    client omit it, and a request with no Origin cannot be a drive-by from a web
    page — browsers always set it cross-site.
    """
    if not check_origin():
        return True, ""
    if not origin:
        # Host still has to look like us, which is what stops DNS rebinding:
        # the attacker's domain resolves to 127.0.0.1 but the Host header keeps
        # their name on it.
        if host_header and not _is_loopback(host_header):
            allowed = (os.getenv("JARVIS_ALLOWED_HOSTS", "") or "").split(",")
            if host_header.split(":")[0] not in [a.strip() for a in allowed if a.strip()]:
                return False, (f"Host '{host_header}' is not recognised. Reach Jarvis "
                               f"at 127.0.0.1, or list this name in "
                               f"JARVIS_ALLOWED_HOSTS.")
        return True, ""
    try:
        parsed = urlparse(origin)
    except Exception:
        return False, f"Malformed Origin '{origin[:60]}'."
    if _is_loopback(parsed.hostname or ""):
        return True, ""
    allowed = [a.strip() for a in
               (os.getenv("JARVIS_ALLOWED_ORIGINS", "") or "").split(",") if a.strip()]
    if origin in allowed:
        return True, ""
    return False, (f"Blocked a request from {origin}. Only pages served from "
                   f"localhost may drive Jarvis — a web page you visit must not "
                   f"be able to type on your keyboard.")


def is_control_path(path: str) -> bool:
    return any(path.startswith(p) for p in CONTROL_PREFIXES)


def is_open_path(path: str) -> bool:
    return path in OPEN_PATHS or any(path.startswith(p) for p in OPEN_PREFIXES)


def token_ok(supplied: str) -> bool:
    if not supplied:
        return False
    return secrets.compare_digest(supplied.strip(), token())


def authorize(path: str, method: str, headers) -> tuple[bool, int, str]:
    """
    The one decision. Returns (allowed, status_code, message).

    Order matters: origin first (cheapest and blocks the drive-by case), then
    the desktop-control switch, then the token.
    """
    if is_open_path(path):
        return True, 200, ""

    ok, msg = origin_ok(headers.get("origin", ""), headers.get("host", ""))
    if not ok:
        return False, 403, msg

    if is_control_path(path) and not desktop_control_enabled():
        return False, 423, ("Desktop control is switched off. Jarvis can still "
                            "think, plan and run the freelance engine — it just "
                            "won't touch your keyboard, mouse or shell. Turn it "
                            "back on with DESKTOP_CONTROL_ENABLED=1.")

    if require_token():
        supplied = (headers.get("x-jarvis-token", "")
                    or headers.get("authorization", "").removeprefix("Bearer ").strip())
        if not token_ok(supplied):
            return False, 401, ("This Jarvis needs a token because it is not on "
                                "localhost. The token is in backend/.jarvis_token "
                                "— send it as the X-Jarvis-Token header.")
    return True, 200, ""


def status() -> dict:
    """What is protecting this instance right now, in plain words."""
    host = os.getenv("JARVIS_HOST", "127.0.0.1")
    loopback = _is_loopback(host)
    return {
        "bound_to": host,
        "loopback_only": loopback,
        "token_required": require_token(),
        "token_file": str(TOKEN_FILE) if TOKEN_FILE.exists() else None,
        "origin_checked": check_origin(),
        "desktop_control": desktop_control_enabled(),
        "summary": (
            "Loopback only, so only programs on this PC can reach Jarvis. "
            "Web pages are blocked by the Origin check."
            if loopback and check_origin() else
            "Reachable beyond this PC — a token is required for every request."
            if not loopback else
            "Loopback only, but the Origin check is OFF: any web page you visit "
            "could drive Jarvis. Turn JARVIS_CHECK_ORIGIN back on."),
        "controls": {
            "JARVIS_REQUIRE_TOKEN": "force the token on even for local use",
            "JARVIS_CHECK_ORIGIN": "reject requests from web pages (leave on)",
            "DESKTOP_CONTROL_ENABLED": "0 disables keyboard/mouse/shell entirely",
            "JARVIS_ALLOWED_ORIGINS": "extra origins, comma separated",
        },
    }
