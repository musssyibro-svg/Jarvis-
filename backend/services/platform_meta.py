"""
services/platform_meta.py — what KIND each platform is, and how you apply there.

This is the fix for the FAILED-bid cascade in the screenshots: the executor was
treating every platform like Freelancer and hunting for a "Place Bid" button.
But RemoteOK / We Work Remotely / Remote.co are job BOARDS — you apply through
an external link, there is no on-platform bid form. Trying to submit a bid there
can only ever fail.

Kinds:
  bid     — you submit a proposal/bid ON the platform (Freelancer, PeoplePerHour,
            Guru, Upwork). Automatable submission, needs a logged-in session.
  board   — aggregator; each job links OUT to the employer's own form
            (RemoteOK, WeWorkRemotely, Remote.co, Wellfound). Jarvis opens the
            apply page for you — it cannot robotically fill an unknown 3rd-party form.
  talent  — clients contact YOU from your profile (Hubstaff Talent, Contra).
            "Applying" means keeping the profile strong, not submitting bids.
  micro   — task marketplaces (Clickworker, Zuodao). Tasks are claimed, not bid on.

`submittable(platform)` is the gate the executor uses: only 'bid' platforms get
an automated submission attempt. Everything else is opened for the user, and
marked with a clear, non-failure status.
"""

PLATFORM_KIND = {
    "freelancer":     "bid",
    "peopleperhour":  "bid",
    "upwork":         "bid",
    "guru":           "bid",
    "fiverr":         "talent",     # gigs, not bids — client comes to you
    "remoteok":       "board",
    "weworkremotely": "board",
    "remoteco":       "board",
    "remote.co":      "board",
    "wellfound":      "board",
    "contra":         "talent",
    "hubstaff":       "talent",
    "clickworker":    "micro",
    "zuodao":         "micro",
}

# Human-friendly labels used in feed messages.
KIND_LABEL = {
    "bid":    "bid platform",
    "board":  "job board (external apply)",
    "talent": "talent profile (clients contact you)",
    "micro":  "microtask marketplace",
}


def kind(platform: str) -> str:
    return PLATFORM_KIND.get((platform or "").strip().lower(), "board")


def submittable(platform: str) -> bool:
    """True only for platforms where Jarvis can place a bid/proposal itself."""
    return kind(platform) == "bid"


def needs_login(platform: str) -> bool:
    """Bid platforms require an authenticated session to submit."""
    return kind(platform) == "bid"


def apply_note(platform: str) -> str:
    k = kind(platform)
    if k == "board":
        return ("This is a job board — I opened the employer's application page "
                "for you. Boards don't accept automated bids; paste the proposal "
                "and apply there in one step.")
    if k == "talent":
        return ("This is a talent platform — clients reach out from your profile. "
                "Keep your profile and skills sharp; there's no bid to submit.")
    if k == "micro":
        return ("Microtask site — tasks are claimed, not bid on. Opened it for you.")
    return ""


# ── Can this configuration actually send anything? ───────────────────────────

def readiness(scanning: list[str], sessions: list[dict] | None = None) -> dict:
    """
    Answer the question the Earn page never asked: with the platforms you scan
    and the sites you're logged into, can Jarvis submit ANYTHING at all?

    This exists because of a real configuration that produced 15 drafted
    proposals and zero possible submissions:

        scanning : remoteok(board) peopleperhour(bid) freelancer(bid) weworkremotely(board)
        logged in: upwork fiverr hubstaff contra wellfound

    The two platforms that accept a bid were the two with no session, and the
    two being scanned most were boards that never accept one. The overlap was
    empty. Jarvis showed a green "earning for you" and a queue of drafts that
    could never be sent — which is exactly what "the freelance section is just
    an advert" means, and it was true.

    Nothing here is a failure. A board is a perfectly good thing to scan; the
    proposal is still worth having when you apply by hand. What was missing is
    Jarvis SAYING so, instead of implying an automated pipeline that cannot run.
    """
    scanning = [str(p).strip().lower() for p in (scanning or []) if p]
    live = {(s.get("platform") or "").strip().lower()
            for s in (sessions or []) if s.get("logged_in") is True}

    bid_sites = [p for p in scanning if submittable(p)]
    boards = [p for p in scanning if kind(p) == "board"]
    ready = [p for p in bid_sites if p in live]
    need_login = [p for p in bid_sites if p not in live]

    if ready:
        head = (f"Can submit automatically on {', '.join(ready)}. "
                f"Everything else it finds is drafted for you to send by hand.")
    elif bid_sites:
        head = (f"Nothing can be submitted automatically right now: "
                f"{', '.join(need_login)} accept bids but you're not logged in. "
                f"Log in once under Platform Logins and Jarvis reuses the session.")
    elif scanning:
        head = (f"Nothing here can be submitted automatically — "
                f"{', '.join(scanning)} "
                f"{'are job boards' if len(scanning) > 1 else 'is a job board'}, "
                f"where you apply on the employer's own site. Jarvis drafts the "
                f"proposal and opens the page; the sending is yours.")
    else:
        head = "No platforms selected, so there is nothing to scan."

    return {
        "can_submit": bool(ready),
        "ready": ready,
        "need_login": need_login,
        "boards": boards,
        "headline": head,
        # The honest framing for the toggle: scanning IS working even when
        # submitting can't. Conflating the two is what made this look broken.
        "scanning_is_useful": bool(scanning),
    }
