"""
"I press approve all but I don't know if it sent it."

The old post-submit check slept exactly 3 seconds, read the page once, and
called anything without a known phrase "submitted, but unconfirmed". Two
consequences, both bad:

  * A site that confirmed at 3.5s was recorded as unconfirmed EVERY time, which
    trains you to ignore that warning — and it is the same warning shown when a
    submission genuinely failed.
  * A click that did nothing at all (disabled button, missing required field)
    was reported as "submitted". A false Done, on a real client's job.

Now it polls, and it distinguishes four outcomes. The one that matters most is
`unchanged`: form still open, URL never moved — nothing was sent, and it says so.

Also asserted here: a submission is NEVER retried. A submit that times out may
have arrived and only lost the response; clicking again puts a second proposal
in front of a real client under the user's name.
"""

import asyncio
from pathlib import Path

import pytest

from services import bid_executor as be


class FakePage:
    def __init__(self, text="", url="http://job", form=True):
        self.text, self.url, self._form = text, url, form

    async def content(self):
        return self.text

    async def query_selector(self, _sel):
        return object() if self._form else None


def verdict(text, form, url, url_before="http://job", seconds=1.5):
    page = FakePage(text, url, form)
    return asyncio.run(be._wait_for_confirmation(page, url_before, True, seconds))


@pytest.mark.parametrize(
    "phrase",
    [
        "Bid placed successfully",
        "Your proposal submitted",
        "Application sent",
        "we have received your application",
        "投标成功",
    ],
)
def test_the_site_saying_yes_is_recorded_as_sent(phrase):
    v, _ = verdict(f"<div>{phrase}</div>", form=False, url="http://job/done")
    assert v == "sent"


@pytest.mark.parametrize(
    "phrase",
    [
        "You already bid on this project",
        "Could not be placed",
        "This project is closed",
        "Please complete your profile",
    ],
)
def test_the_site_saying_no_is_recorded_as_rejected(phrase):
    v, why = verdict(f"<div>{phrase}</div>", form=True, url="http://job")
    assert v == "rejected"
    assert why, "a rejection must say what the page said"


def test_a_click_that_did_nothing_is_never_called_submitted():
    """The important one. Form still there, URL unmoved: nothing was sent."""
    v, why = verdict("<form>bid form still here</form>", form=True, url="http://job")
    assert v == "unchanged"
    assert "still open" in why


def test_form_closing_and_navigating_counts_as_sent_without_words():
    """Not every site says anything. Structure is evidence too."""
    v, why = verdict("<div>ok</div>", form=False, url="http://job/manage")
    assert v == "sent"
    assert "moved to" in why


def test_refusal_wins_over_a_success_word_in_the_same_page():
    """ "Your bid could not be placed" contains "your bid"."""
    v, _ = verdict("<div>Your bid could not be placed</div>", form=True, url="http://job")
    assert v == "rejected"


def test_a_submission_is_never_retried():
    """
    browser_agent.with_retry exists for idempotent calls. bid_executor must not
    use it: a retried submit can send a second proposal to a real client.
    """
    # Comments are allowed to mention it (and one does, explaining why not).
    # What must not exist is a CALL.
    code = [
        ln
        for ln in Path(be.__file__).read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    ]
    calls = [ln.strip() for ln in code if "with_retry(" in ln]
    assert not calls, (
        "bid_executor must never retry a submission — a submit that timed out "
        f"may already have arrived. Found: {calls}"
    )


def test_the_unchanged_verdict_reaches_the_user_as_a_failure():
    """A dead submit must not be filed as success anywhere downstream."""
    src = Path(be.__file__).read_text(encoding="utf-8")
    i = src.index('if confirmed == "unchanged":')
    block = src[i : i + 700]
    assert '"success": False' in block
    assert "Nothing was sent" in block
