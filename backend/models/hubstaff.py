"""
models/hubstaff.py
Hubstaff Talent jobs + applications table definitions.
"""

from models.db import conn


def init_hubstaff_tables() -> None:
    with conn() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS hubstaff_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT UNIQUE,
                title       TEXT,
                description TEXT,
                skills      TEXT,        -- JSON array
                company     TEXT,
                link        TEXT,
                date_posted TEXT,
                scraped_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS hubstaff_applications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT,
                job_title       TEXT,
                company         TEXT,
                application_msg TEXT,
                status          TEXT DEFAULT 'sent',
                employer_reply  TEXT,
                got_reply       INTEGER DEFAULT 0,
                created_at      TEXT,
                updated_at      TEXT
            );
            """
        )
