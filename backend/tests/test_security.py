"""
Regression tests for the things that make Jarvis dangerous if they slip.

Jarvis can type on the user's keyboard and drive a browser already signed in to
their accounts. Every test here guards a rule from CLAUDE.md, and every one of
them maps to a real leak or a real bypass that has happened in this repo.
"""
import pytest

from services import auth, config

# ── The gate ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("origin,host", [
    ("http://evil.example.com", "127.0.0.1:8000"),
    ("https://attacker.test", "localhost:8000"),
])
def test_foreign_origin_is_refused(origin, host):
    """
    CORS is NOT a defence. It governs whether a page may READ a response, not
    whether the request is delivered — and a POST that starts typing has
    already done its damage by then. The check has to happen before the route.
    """
    ok, _ = auth.origin_ok(origin, host)
    assert ok is False


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000",
])
def test_the_real_console_is_allowed(origin):
    ok, why = auth.origin_ok(origin, "127.0.0.1:8000")
    assert ok is True, why


def test_dns_rebinding_host_is_refused():
    """
    A name that resolves to 127.0.0.1 is not the same as 127.0.0.1. Trusting
    the Host header verbatim is what DNS rebinding attacks.
    """
    ok, _ = auth.origin_ok("http://jarvis.attacker.test", "jarvis.attacker.test")
    assert ok is False


def test_health_is_open_so_the_launcher_can_wait_for_it():
    """START.bat polls /health before opening the browser. If the gate closes
    it, the launcher waits forever and reports a working backend as offline."""
    assert auth.is_open_path("/health") is True


def test_anything_that_types_is_a_control_path():
    """Control paths need a token. If one of these is ever reclassified as
    open, a drive-by request can drive the keyboard."""
    for path in ("/agents/desktop/type_text", "/chat", "/automation/execute-approved"):
        assert auth.is_control_path(path) or not auth.is_open_path(path), (
            f"{path} is reachable without a token"
        )


# ── Credentials must never appear in anything the user sends me ──────────────

@pytest.mark.parametrize("key", [
    "ai_deepseek_api_key", "ai_kimi_api_key", "ai_openai_api_key",
])
def test_api_keys_are_recognised_as_secret(key):
    assert config.is_secret(key) is True


@pytest.mark.parametrize("key", ["search_engine", "ai_route_plan", "vision_model"])
def test_ordinary_settings_are_not_secret(key):
    assert config.is_secret(key) is False


def test_effective_settings_never_expose_a_key():
    """
    /settings/effective is embedded verbatim in the runtime report the user
    downloads and sends me. It leaked API keys once. It must not again.
    """
    secret = "sk-THIS-MUST-NEVER-APPEAR-1234567890"
    config.set("ai_deepseek_api_key", secret)
    try:
        blob = repr(config.effective())
        assert secret not in blob, "an API key reached the runtime report"
        assert "ai_deepseek_api_key" in blob, "the setting vanished instead of being masked"
    finally:
        config.set("ai_deepseek_api_key", "")


def test_a_masked_value_is_still_recognisable():
    """Masking to nothing is unhelpful — you can't tell 'unset' from 'hidden'."""
    config.set("ai_kimi_api_key", "sk-abcdefghijklmnop")
    try:
        shown = str(config.effective().get("ai_kimi_api_key", ""))
        assert shown and "abcdefghijklmnop" not in shown
    finally:
        config.set("ai_kimi_api_key", "")


# ── Teaching by demonstration must not record passwords ──────────────────────

@pytest.mark.parametrize("title", [
    "Sign in - Freelancer", "Login | Upwork", "Enter your password",
    "登录 - QQ", "密码", "Two-factor authenticate", "Unlock vault",
])
def test_login_windows_are_recognised_in_both_languages(title):
    """
    Windows here may be in Chinese. A password box titled 登录 must be caught
    by the same guard as one titled "Sign in", or the protection only works in
    English on a machine that mostly isn't.
    """
    from services import teach
    assert teach._looks_secret(title) is True


def test_demonstration_emits_a_placeholder_not_the_keystrokes():
    """
    "Watch me do it" records what the user does. If they type into a login box
    while it's watching, the workflow must carry "there's a login here" and
    nothing else — the keystrokes are dropped at record time and never reach
    distil() at all.
    """
    from services import teach

    t0 = 1_700_000_000.0
    events = [
        {"t": t0, "kind": "key", "char": "n", "key": None,
         "app": "notepad.exe", "title": "Untitled - Notepad"},
        # What on_key() writes when the focused window looks like a login: no
        # char field exists, because the character was never captured.
        {"t": t0 + 1, "kind": "secret",
         "app": "chrome.exe", "title": "Sign in - Freelancer"},
    ]
    steps = teach.distil(events)
    blob = repr(steps)

    assert "credential" in blob, "the login step vanished instead of being marked"
    assert "Sign in - Freelancer" in blob, "the placeholder should say WHERE to log in"

    # The one thing that must be true: the credential step carries no text to
    # replay. A placeholder that still holds the password is not a placeholder.
    cred = next(s for s in steps if s.get("action") == "credential")
    assert "text" not in (cred.get("params") or {})


# ── Simulation must never actually do anything ───────────────────────────────

def test_simulating_a_task_executes_nothing(monkeypatch):
    """
    "Show me what you would do" is only useful if it is guaranteed not to do
    it. Simulation runs against a live desktop and a logged-in browser.
    """
    from services import simulate

    fired = []
    import agents.desktop_agent as da
    for name in ("open_app", "type_text", "press", "click"):
        if hasattr(da, name):
            monkeypatch.setattr(da, name, lambda *a, _n=name, **k: fired.append(_n))

    simulate.task("open notepad and type hello")
    assert fired == [], f"simulation actually ran: {fired}"
