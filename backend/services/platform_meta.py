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
