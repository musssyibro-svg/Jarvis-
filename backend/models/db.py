"""
models/db.py — Jarvis v3 unified SQLite schema
All tables created on first startup. Never drops existing data.
"""
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DB_PATH  = BASE_DIR / os.getenv("JARVIS_DB", "jarvis.db")


def conn() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    with conn() as db:
        db.executescript("""
-- ── Core ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS proposals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT,
    platform        TEXT    DEFAULT 'freelancer',
    job_title       TEXT,
    job_desc        TEXT,
    budget          TEXT,
    job_link        TEXT,
    skills          TEXT,
    proposal_text   TEXT,
    confidence      INTEGER DEFAULT 0,
    can_auto_work   INTEGER DEFAULT 0,
    work_type       TEXT,
    work_reason     TEXT,
    status          TEXT    DEFAULT 'draft',
    work_output     TEXT,
    work_status     TEXT    DEFAULT 'pending',
    got_reply       INTEGER DEFAULT 0,
    won             INTEGER DEFAULT 0,
    created_at      TEXT,
    updated_at      TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sender          TEXT,
    message_preview TEXT,
    full_message    TEXT,
    received_at     TEXT,
    thread_url      TEXT,
    is_read         INTEGER DEFAULT 0,
    reply_draft     TEXT,
    created_at      TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT, note TEXT, done INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT, body TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, role TEXT, content TEXT, created_at TEXT
);

-- ── Hubstaff ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hubstaff_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT UNIQUE, title TEXT, description TEXT,
    skills      TEXT, company TEXT, link TEXT, date_posted TEXT,
    platform    TEXT DEFAULT 'hubstaff', scraped_at TEXT
);
CREATE TABLE IF NOT EXISTS hubstaff_applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT, job_title TEXT, company TEXT,
    application_msg TEXT, status TEXT DEFAULT 'draft',
    employer_reply  TEXT, got_reply INTEGER DEFAULT 0,
    created_at TEXT, updated_at TEXT
);

-- ── Fiverr ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fiverr_gigs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, category TEXT, description TEXT, tags TEXT, pricing TEXT,
    status TEXT DEFAULT 'active', orders INTEGER DEFAULT 0, rating REAL DEFAULT 0.0,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fiverr_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_name TEXT, gig_title TEXT, message_preview TEXT, full_message TEXT,
    thread_url TEXT, is_read INTEGER DEFAULT 0, reply_draft TEXT, custom_offer TEXT,
    received_at TEXT, created_at TEXT
);

-- ── Clickworker ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clickworker_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT UNIQUE, title TEXT, category TEXT, description TEXT,
    reward          REAL DEFAULT 0.0, estimated_time INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'available',
    platform        TEXT DEFAULT 'clickworker', fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS clickworker_completed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT, title TEXT, reward REAL DEFAULT 0.0, completed_at TEXT, notes TEXT
);

-- ── Zuodao ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS zuodao_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT UNIQUE, title TEXT, category TEXT, description TEXT,
    reward          TEXT, deadline TEXT, status TEXT DEFAULT 'available',
    platform        TEXT DEFAULT 'zuodao', fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS zuodao_submissions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT, title TEXT, output TEXT, status TEXT DEFAULT 'draft',
    submitted_at TEXT, created_at TEXT
);

-- ── Platform jobs (unified store) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS platform_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT, platform TEXT, title TEXT, description TEXT,
    skills      TEXT, company TEXT, link TEXT, budget TEXT, date_posted TEXT,
    scraped_at  TEXT,
    UNIQUE(job_id, platform)
);

-- ── Automation queue ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS automation_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    platform     TEXT, job_id TEXT, job_title TEXT, action TEXT,
    payload      TEXT, status TEXT DEFAULT 'pending',
    created_at   TEXT, processed_at TEXT
);

-- ── Memory ───────────────────────────────────────────────────────────────────
-- NOTE: agent learning memory lives in the v5_memory_patterns / v5_platform_memory
-- tables defined in V5_SCHEMA below. The older memory_patterns / platform_memory /
-- outcome_log tables were removed in Phase A cleanup: they were created but never
-- written to (always returned empty) and are superseded by the v5_ tables.
        """)

# ── V5 tables (appended) ─────────────────────────────────────────────────────
V5_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    goal         TEXT,
    plan_json    TEXT,
    status       TEXT DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    created_at   TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS automation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT,
    action      TEXT,
    params_json TEXT,
    result_json TEXT,
    success     INTEGER DEFAULT 0,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS client_responses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT,
    client_name TEXT,
    message     TEXT,
    sentiment   TEXT DEFAULT 'neutral',
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS memory_kv (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS v5_memory_patterns (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT,
    job_type         TEXT,
    proposal_snippet TEXT,
    won              INTEGER DEFAULT 0,
    client_response  TEXT,
    notes            TEXT,
    created_at       TEXT
);

CREATE TABLE IF NOT EXISTS v5_platform_memory (
    platform     TEXT PRIMARY KEY,
    total_sent   INTEGER DEFAULT 0,
    total_won    INTEGER DEFAULT 0,
    win_rate     REAL DEFAULT 0.0,
    last_updated TEXT
);
"""

def init_v5(db_conn):
    db_conn.executescript(V5_SCHEMA)
