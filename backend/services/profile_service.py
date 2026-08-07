"""
services/profile_service.py — Persistent freelance profile.

The single source of truth for who the user is when Jarvis writes proposals:
name, skills, hourly rate, portfolio highlights, intro template, categories.
Stored as JSON in the existing `settings` table (key: freelance_profile), so it
survives restarts and is editable from the Auto Mode UI.

ProposalAgent injects this into every LLM prompt — the root fix for generic
or empty proposals: the model finally knows the applicant.
"""
import json

from models.db import conn

PROFILE_KEY = "freelance_profile"

DEFAULT_PROFILE = {
    "name":         "Ibrahim",
    "skills":       "Python, automation, web scraping, AI integration, FastAPI",
    "hourly_rate":  "15",
    "currency":     "USD",
    "portfolio":    "",
    "intro":        "",           # optional standard opening line
    "categories":   "automation, scripting, data, web scraping, AI",
    "min_score":    30,           # jobs below this score are ignored
    "max_generate": 10,           # proposals per cycle cap
    "auto_submit":  False,        # True = submit approved without extra click
}


class UnreadableProfile(RuntimeError):
    """Saved profile exists but couldn't be read. NOT the same as 'no profile'."""


def get_profile(strict: bool = False) -> dict:
    """
    Your freelance identity — name, rate, portfolio, skills.

    `strict` is for WRITERS, and the blast radius here is the worst of the
    three: save_profile() is get_profile() + patch + write, so one failed read
    silently reverted a real name and rate to the hardcoded DEFAULT_PROFILE —
    and this profile is what goes into every proposal sent to a real client.
    You would be bidding under the wrong name at the wrong rate, with the save
    reporting success.
    """
    try:
        with conn() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?",
                             (PROFILE_KEY,)).fetchone()
        if row and row["value"]:
            saved = json.loads(row["value"])
            return {**DEFAULT_PROFILE, **saved}
        return dict(DEFAULT_PROFILE)
    except Exception as e:
        if strict:
            raise UnreadableProfile(
                f"couldn't read your saved profile ({str(e)[:80]}), so I won't "
                f"overwrite it with defaults") from e
        return dict(DEFAULT_PROFILE)


def save_profile(patch: dict) -> dict:
    try:
        profile = get_profile(strict=True)
    except UnreadableProfile as e:
        return {"ok": False, "error": str(e),
                "what_to_do": "Try again in a moment — something else was using "
                              "the database."}
    for k, v in (patch or {}).items():
        if k in DEFAULT_PROFILE and v is not None:
            profile[k] = v
    with conn() as db:
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                   (PROFILE_KEY, json.dumps(profile)))
    return profile


def prompt_block(profile: dict | None = None) -> str:
    """The applicant block injected into every proposal prompt."""
    p = profile or get_profile()
    lines = [f"Applicant: {p['name']}",
             f"Skills: {p['skills']}"]
    if p.get("hourly_rate"):
        lines.append(f"Hourly rate: {p['hourly_rate']} {p.get('currency','USD')}")
    if p.get("portfolio"):
        lines.append(f"Portfolio / past work: {p['portfolio']}")
    if p.get("categories"):
        lines.append(f"Preferred categories: {p['categories']}")
    if p.get("intro"):
        lines.append(f"Standard intro style: {p['intro']}")
    return "\n".join(lines)
