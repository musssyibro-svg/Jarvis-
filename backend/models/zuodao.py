"""models/zuodao.py"""
from models.db import conn


def init_zuodao_tables():
    with conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS zuodao_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE, title TEXT, category TEXT,
                description TEXT, reward TEXT, deadline TEXT,
                status TEXT DEFAULT 'available',
                platform TEXT DEFAULT 'zuodao', fetched_at TEXT
            );
            CREATE TABLE IF NOT EXISTS zuodao_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT, title TEXT, output TEXT,
                status TEXT DEFAULT 'draft',
                submitted_at TEXT, created_at TEXT
            );
        """)
