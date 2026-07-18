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
    auto_tier TEXT,
    capture_time TEXT,
    iso INTEGER,
    shutter TEXT,
    aperture TEXT,
    focal TEXT,
    cam TEXT,
    size TEXT
);
"""


_META_COLUMNS = ["capture_time", "iso", "shutter", "aperture", "focal", "cam", "size"]


def _migrate(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
    for col in _META_COLUMNS:
        if col not in existing:
            coltype = "INTEGER" if col == "iso" else "TEXT"
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col} {coltype}")
    conn.commit()


def connect(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: pywebview 把 js_api 方法调用派发到独立的后台线程执行，
    # 跟创建这个连接的主线程不是同一个线程，sqlite3 默认会拒绝跨线程使用同一连接。
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def insert_photo(conn, path, folder, filename, thumbnail):
    conn.execute(
        "INSERT OR IGNORE INTO photos (path, folder, filename, thumbnail) VALUES (?, ?, ?, ?)",
        (str(path), folder, filename, thumbnail),
    )
    conn.commit()


def list_photos(conn):
    # 按 id 倒序 = 按导入顺序倒序，最近导入的排最前面。id 是自增主键，天然反映
    # 每张照片被插入（导入）的先后。这样用户一导入完，新照片就出现在列表顶部，
    # 不会像"按文件名排序"那样被打散、埋进已有的上千张照片中间找不到。
    cur = conn.execute(
        """SELECT id, path, folder, filename, thumbnail, tier, auto_tier,
                  capture_time, iso, shutter, aperture, focal, cam, size
           FROM photos
           ORDER BY (capture_time IS NULL), capture_time DESC, id DESC"""
    )
    return cur.fetchall()


def update_metadata(conn, photo_id, meta):
    cols = [c for c in _META_COLUMNS if c in meta]
    if not cols:
        return
    assignments = ", ".join(f"{c} = ?" for c in cols)
    values = [meta[c] for c in cols] + [photo_id]
    conn.execute(f"UPDATE photos SET {assignments} WHERE id = ?", values)
    conn.commit()


def set_manual_tier(conn, photo_id, tier):
    conn.execute("UPDATE photos SET tier = ? WHERE id = ?", (tier, photo_id))
    conn.commit()


def get_paths_for_ids(conn, photo_ids):
    if not photo_ids:
        return []
    placeholders = ",".join("?" for _ in photo_ids)
    cur = conn.execute(
        f"SELECT path FROM photos WHERE id IN ({placeholders}) ORDER BY id",
        list(photo_ids),
    )
    return [row["path"] for row in cur.fetchall()]


def delete_photos(conn, photo_ids):
    if not photo_ids:
        return
    placeholders = ",".join("?" for _ in photo_ids)
    conn.execute(f"DELETE FROM photos WHERE id IN ({placeholders})", list(photo_ids))
    conn.commit()


def list_folders(conn):
    cur = conn.execute(
        "SELECT folder, COUNT(*) AS count FROM photos GROUP BY folder ORDER BY MAX(id) DESC"
    )
    return [{"folder": row["folder"], "count": row["count"]} for row in cur.fetchall()]
