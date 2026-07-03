"""
platforms/base.py
Abstract base for all job platforms.
Every platform must implement: scan_jobs(), generate_application(), submit_application(), check_replies()
"""

from abc import ABC, abstractmethod


class BasePlatform(ABC):
    name: str = "base"

    @abstractmethod
    def scan_jobs(self, max_jobs: int = 20) -> list[dict]:
        """
        Return list of job dicts with keys:
        job_id, title, description, skills, company, link, date_posted, platform
        """
        ...

    @abstractmethod
    def generate_application(self, job: dict, your_name: str, your_skills: str) -> str:
        """Return AI-written application message string."""
        ...

    def submit_application(self, job: dict, application_text: str) -> dict:
        """
        Attempt automated submission via browser.
        Returns {"submitted": bool, "message": str}
        Default: manual — platform must override if automation is possible.
        """
        return {"submitted": False, "message": "Manual submission required. Copy the application text."}

    def check_replies(self) -> list[dict]:
        """
        Check for new replies/messages on this platform.
        Returns list of message dicts. Override per-platform.
        """
        return []
