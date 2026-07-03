"""
models/fiverr.py
Fiverr gigs + messages table definitions.
"""

from models.db import conn


def init_fiverr_tables() -> None:
    with conn() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS fiverr_gigs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT,
                category    TEXT,
                description TEXT,
                tags        TEXT,        -- JSON array
                pricing     TEXT,        -- JSON {basic, standard, premium}
                status      TEXT DEFAULT 'active',
                orders      INTEGER DEFAULT 0,
                rating      REAL DEFAULT 0.0,
                created_at  TEXT,
                updated_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS fiverr_messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_name      TEXT,
                gig_title       TEXT,
                message_preview TEXT,
                full_message    TEXT,
                thread_url      TEXT,
                is_read         INTEGER DEFAULT 0,
                reply_draft     TEXT,
                custom_offer    TEXT,
                received_at     TEXT,
                created_at      TEXT
            );
            """
        )
