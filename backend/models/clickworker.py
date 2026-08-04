"""models/clickworker.py"""
from models.db import conn


def init_clickworker_tables():
    with conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS clickworker_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE, title TEXT, category TEXT,
                description TEXT, reward REAL DEFAULT 0.0,
                estimated_time INTEGER DEFAULT 0,
                status TEXT DEFAULT 'available',
                platform TEXT DEFAULT 'clickworker', fetched_at TEXT
            );
            CREATE TABLE IF NOT EXISTS clickworker_completed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT, title TEXT, reward REAL DEFAULT 0.0,
                completed_at TEXT, notes TEXT
            );
        """)
