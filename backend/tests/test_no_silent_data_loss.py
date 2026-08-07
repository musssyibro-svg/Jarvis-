"""
Four handlers that swallowed a READ and then wrote back over what they hadn't read.

Every one of these was reproduced against a throwaway database before it was
fixed — they are not readings of the code. The shape is always the same:

    facts = _load()          # raises, returns {} instead
    facts[field] = value     # the one new thing
    _save(facts)             # INSERT OR REPLACE — everything else is gone

and the caller reports success. A locked database is enough to trigger it:
several background pollers share one connection with a 5s busy timeout.

The fourth is worse than data loss. _bid_form_present returned False when it
COULDN'T LOOK, and False there means "the form is gone", which the confirmation
logic reads as evidence the bid was submitted. Playwright raises exactly that
on a query during navigation — the instant after a Submit click.
"""

import pytest


def _break_db(monkeypatch, module):
    """Make this module's next database read fail, and nothing else."""

    def boom(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(module, "conn", boom)


# ── Facts you stated ─────────────────────────────────────────────────────────


def test_a_failed_read_never_wipes_your_remembered_facts(monkeypatch):
    """
    Proven behaviour before the fix: four stated facts became one, and
    remember() answered "Got it — I'll remember that."
    """
    from services import persona

    _break_db(monkeypatch, persona)
    out = persona.remember("location", "shenzhen")
    assert out["ok"] is False, "claimed success while overwriting everything"
    assert "won't overwrite" in out["error"]


def test_forget_refuses_on_an_unreadable_store(monkeypatch):
    from services import persona

    _break_db(monkeypatch, persona)
    assert persona.forget("browser")["ok"] is False


def test_readers_still_degrade_quietly(monkeypatch):
    """
    A missing fact is a small thing and must not break chat. Only WRITERS are
    strict — making reads raise too would turn a locked database into a
    complete outage.
    """
    from services import persona

    _break_db(monkeypatch, persona)
    assert persona.all_facts() == {}
    assert persona.prompt_block() == ""


# ── Your freelance identity ──────────────────────────────────────────────────


def test_a_failed_read_never_reverts_your_name_and_rate(monkeypatch):
    """
    The worst blast radius of the three: this profile goes into every proposal
    sent to a real client. Proven before the fix — a real name and rate
    silently became the hardcoded defaults, and the save reported success.
    """
    from services import profile_service

    _break_db(monkeypatch, profile_service)
    out = profile_service.save_profile({"hourly_rate": "45"})
    assert out["ok"] is False
    assert "won't overwrite" in out["error"]


# ── An engine you stopped ────────────────────────────────────────────────────


def test_an_unreadable_config_does_not_restart_a_paused_engine(monkeypatch):
    """
    DEFAULTS["enabled"] is True and the loop reads config on every tick, so a
    single failed read turned a paused engine back on — and the next cycle's
    own save persisted enabled=True, making it stick.
    """
    from services import income_engine

    _break_db(monkeypatch, income_engine)
    with pytest.raises(income_engine.UnreadableConfig):
        income_engine.get_config(strict=True)
    # Non-strict readers still get something usable.
    assert income_engine.get_config()["enabled"] in (True, False)


# ── A bid the site never acknowledged ────────────────────────────────────────


def test_couldnt_check_the_form_is_not_evidence_of_submission():
    """
    The whole bug in one line: `not await _bid_form_present(page)`.

    When the check couldn't run it returned False, `not False` is True, and
    "the form is gone" became "the bid was sent" — with a receipt, a done row,
    and a green tick, over a page that showed only a captcha.
    """
    import asyncio
    import inspect

    from services import bid_executor

    class _DeadPage:
        url = "https://example.com/project/1"

        async def query_selector(self, sel):
            raise RuntimeError("Execution context was destroyed")

    loop = asyncio.new_event_loop()
    try:
        got = loop.run_until_complete(bid_executor._bid_form_present(_DeadPage()))
    finally:
        loop.close()
    assert got is None, f"an unreadable page returned {got!r}, which is usable as evidence"

    # And the caller must test it identity-wise, not truthily.
    src = inspect.getsource(bid_executor._wait_for_confirmation)
    assert "_bid_form_present(page) is False" in src, (
        "the confirmation path uses `not ...`, so None counts as 'form gone'"
    )
