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
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT UNIQUE,
                phone TEXT,
                role TEXT,
                business_name TEXT,
                pw_salt TEXT,
                pw_hash TEXT,
                created TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT,
                created TEXT,
                expires TEXT
            );
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dealer_id TEXT,
                name TEXT,
                created TEXT,
                UNIQUE (dealer_id, name)
            );
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dealer_id TEXT,
                name TEXT,
                phone TEXT,
                email TEXT,
                business TEXT,
                segment_id INTEGER,
                notes TEXT,
                user_id TEXT,
                invite_token TEXT,
                created TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT,
                sender_id TEXT,
                sender_name TEXT,
                sender_role TEXT,
                kind TEXT,
                body TEXT,
                created TEXT
            );
            CREATE TABLE IF NOT EXISTS checks (
                deal_id TEXT,
                user_id TEXT,
                field TEXT,
                result TEXT,
                note TEXT,
                updated TEXT,
                PRIMARY KEY (deal_id, user_id, field)
            );
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT,
                kind TEXT,
                name TEXT,
                label TEXT,
                mime TEXT,
                size INTEGER,
                sha256 TEXT,
                path TEXT,
                text TEXT,
                text_status TEXT,
                occurred_at TEXT,
                speaker TEXT,
                added TEXT,
                removed INTEGER DEFAULT 0
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
        _add_columns(c, "customers", {"invite_token": "TEXT"})
        _add_columns(c, "deals", {
            "dealer_id": "TEXT", "customer_id": "INTEGER", "description": "TEXT", "deal_type": "TEXT",
            "est_value": "REAL", "advance": "REAL", "due_date": "TEXT", "gst": "TEXT",
            "priority": "TEXT", "channel": "TEXT", "notes": "TEXT", "sent_at": "TEXT",
        })


def _add_columns(c, table: str, cols: dict):
    have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    for name, typ in cols.items():
        if name not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
