import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    folder TEXT NOT NULL,
    filename TEXT NOT NULL,
    thumbnail BLOB,
    tier TEXT,
    auto_tier TEXT
);
"""


def connect(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def insert_photo(conn, path, folder, filename, thumbnail):
    conn.execute(
        "INSERT OR IGNORE INTO photos (path, folder, filename, thumbnail) VALUES (?, ?, ?, ?)",
        (str(path), folder, filename, thumbnail),
    )
    conn.commit()


def list_photos(conn):
    cur = conn.execute(
        "SELECT id, path, folder, filename, thumbnail, tier, auto_tier FROM photos ORDER BY filename"
    )
    return cur.fetchall()


def set_manual_tier(conn, photo_id, tier):
    conn.execute("UPDATE photos SET tier = ? WHERE id = ?", (tier, photo_id))
    conn.commit()
