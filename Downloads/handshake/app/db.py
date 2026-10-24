import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "data/handshake.db")


def conn():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS deals (
                id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT,
                chat_text TEXT,
                messages TEXT,
                terms TEXT,
                agreement TEXT,
                tone TEXT,
                token TEXT,
                otp TEXT,
                created TEXT
            );
            CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT,
                seq INTEGER,
                kind TEXT,
                content_hash TEXT,
                meta TEXT,
                ts TEXT,
                prev_hash TEXT,
                entry_hash TEXT
            );
            """
        )
