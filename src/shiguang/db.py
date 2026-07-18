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
    # check_same_thread=False: pywebview 把 js_api 方法调用派发到独立的后台线程执行，
    # 跟创建这个连接的主线程不是同一个线程，sqlite3 默认会拒绝跨线程使用同一连接。
    conn = sqlite3.connect(db_path, check_same_thread=False)
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
    # 按 id 倒序 = 按导入顺序倒序，最近导入的排最前面。id 是自增主键，天然反映
    # 每张照片被插入（导入）的先后。这样用户一导入完，新照片就出现在列表顶部，
    # 不会像"按文件名排序"那样被打散、埋进已有的上千张照片中间找不到。
    cur = conn.execute(
        "SELECT id, path, folder, filename, thumbnail, tier, auto_tier FROM photos ORDER BY id DESC"
    )
    return cur.fetchall()


def set_manual_tier(conn, photo_id, tier):
    conn.execute("UPDATE photos SET tier = ? WHERE id = ?", (tier, photo_id))
    conn.commit()
