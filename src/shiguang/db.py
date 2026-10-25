import os
import sqlite3
from pathlib import Path

# 架构决策(2026-07-19)：数据库只存"数据"（路径/编号/标签/EXIF），不永久保存缩略图字节。
# 之前 thumbnail BLOB 会让"删缓存"名不副实——图像字节早就永久躺在数据库里，删多少次
# 缓存文件夹都能立刻重新导出。现在缩略图只作为磁盘缓存文件存在（由 scanner/api 写到
# thumb_cache/{id}.jpg），数据库里再找不到任何图像数据。代价：原文件不可访问(拔卡)且
# 缓存文件也被清掉时，那张照片就真的显示不出缩略图/没法评分了，需要插回卡才能恢复。
SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    folder TEXT NOT NULL,
    filename TEXT NOT NULL,
    tier TEXT,
    auto_tier TEXT,
    capture_time TEXT,
    iso INTEGER,
    shutter TEXT,
    aperture TEXT,
    focal TEXT,
    cam TEXT,
    size TEXT,
    rotation INTEGER NOT NULL DEFAULT 0,
    is_card INTEGER NOT NULL DEFAULT 0,
    card_serial TEXT,
    phash TEXT,
    focus_score REAL,
    score_ver INTEGER
);
"""


_META_COLUMNS = ["capture_time", "iso", "shutter", "aperture", "focal", "cam", "size"]


def _migrate(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
    for col in _META_COLUMNS:
        if col not in existing:
            coltype = "INTEGER" if col == "iso" else "TEXT"
            conn.execute(f"ALTER TABLE photos ADD COLUMN {col} {coltype}")
    if "rotation" not in existing:
        conn.execute("ALTER TABLE photos ADD COLUMN rotation INTEGER NOT NULL DEFAULT 0")
    if "is_card" not in existing:
        conn.execute("ALTER TABLE photos ADD COLUMN is_card INTEGER NOT NULL DEFAULT 0")
    if "card_serial" not in existing:
        # 卡卷序列号：认卡+每卡文件夹记忆用。老数据为 NULL(反推不出插的是哪张卡)，
        # 由 api.list_folders 走"盘符兜底"显示，不回归。
        conn.execute("ALTER TABLE photos ADD COLUMN card_serial TEXT")
    if "phash" not in existing:
        # 感知哈希(dHash 64bit 存16位十六进制)：相似去重/连拍分组用，分析趟里算。老数据 NULL→不进堆叠。
        conn.execute("ALTER TABLE photos ADD COLUMN phash TEXT")
    if "focus_score" not in existing:
        # 主体锐度分(评分算出的 subject_vol)：堆叠里选"最锐封面"+组内排序用。NULL→排最后。
        conn.execute("ALTER TABLE photos ADD COLUMN focus_score REAL")
    if "score_ver" not in existing:
        # 这张照片是用第几版评分算法评的(scoring.SCORE_VERSION)。老数据 NULL=按第 0 版算：算法升级后
        # 会算进"待分析"，点一次分析即用新算法重评(手动改过的档保留)。
        conn.execute("ALTER TABLE photos ADD COLUMN score_ver INTEGER")
    if "thumbnail" in existing:
        # 旧库升级：丢弃永久保存的缩略图字节，不再当"记忆"存库（只留编号+标签+EXIF）。
        # 需要 SQLite 3.35+ 支持原生 DROP COLUMN（Python 3.11 自带的版本都满足）。
        conn.execute("ALTER TABLE photos DROP COLUMN thumbnail")
        conn.commit()
        # DROP COLUMN 只改 schema，旧数据占的磁盘页不会自动收回——库文件大小不会变，
        # 用户会以为"删了但没生效"。VACUUM 一次真正把空间要回来；这只在老库升级的
        # 这一次触发，失败(极端情况如磁盘满/无写权限)不影响正常使用，静默跳过即可。
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
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


def insert_photo(conn, path, folder, filename, metadata=None, is_card=0, card_serial=None):
    """插入一条照片记录（只存路径/编号/标签/EXIF这些数据，不存图像字节——缩略图
    由调用方(scanner/api)自行写成磁盘缓存文件）。返回这张照片的 id：不管是刚插入
    的还是路径已存在被 IGNORE 掉的，都会返回它现有的 id，方便调用方据此命名缓存文件。
    is_card=1 表示来自可移动卡(SD等)——侧边栏文件夹记忆只留卡来源的，不留本地磁盘。
    card_serial=卡卷序列号(可为None)，用来"插同一张卡时认出来、只显该卡当前存在的文件夹"。"""
    metadata = metadata or {}
    cols = ["path", "folder", "filename", "is_card", "card_serial"] + [c for c in _META_COLUMNS if c in metadata]
    placeholders = ", ".join("?" for _ in cols)
    values = [str(path), folder, filename, int(is_card), card_serial] + [metadata[c] for c in _META_COLUMNS if c in metadata]
    conn.execute(
        f"INSERT OR IGNORE INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    row = conn.execute("SELECT id FROM photos WHERE path = ?", (str(path),)).fetchone()
    if row is None:
        # INSERT OR IGNORE 吞掉了所有约束冲突，不止 path UNIQUE——比如 folder/filename
        # 传了 None 会撞 NOT NULL、也会被静默忽略。查不到行时给明确报错，别让调用方
        # 拿着 None 去做 row["id"] 得到一个和真实原因毫不相关的 TypeError。
        raise RuntimeError(
            f"insert_photo 之后查不到 path={path!r} 对应的行，"
            f"可能是 folder/filename 等 NOT NULL 约束冲突导致 INSERT OR IGNORE 静默失败"
        )
    return row["id"]


def list_photos(conn):
    # 按 id 倒序 = 按导入顺序倒序，最近导入的排最前面。id 是自增主键，天然反映
    # 每张照片被插入（导入）的先后。这样用户一导入完，新照片就出现在列表顶部，
    # 不会像"按文件名排序"那样被打散、埋进已有的上千张照片中间找不到。
    cur = conn.execute(
        """SELECT id, path, folder, filename, tier, auto_tier,
                  capture_time, iso, shutter, aperture, focal, cam, size, rotation
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


def set_manual_tiers(conn, photo_ids, tier):
    """一批照片一次改成同一档(选择栏批量标记)；单次提交，比逐张 set_manual_tier 快得多。"""
    ids = list(photo_ids or [])
    if not ids:
        return 0
    conn.executemany("UPDATE photos SET tier = ? WHERE id = ?", [(tier, pid) for pid in ids])
    conn.commit()
    return len(ids)


def set_rotation(conn, photo_id, rotation):
    # rotation 归一化到 0/90/180/270，持久化每张的显示旋转角(用户手动转正拍歪的照片)
    conn.execute("UPDATE photos SET rotation = ? WHERE id = ?", (int(rotation) % 360, photo_id))
    conn.commit()


def set_auto_tier(conn, photo_id, auto_tier):
    # 自动分析同时写 auto_tier(记录算法原判，供"用户改了多少"对比) 和 tier(当前生效档)。
    # 与原型一致：分析后 tier 由 null 变成算法档；用户之后手动改判只动 tier、不动 auto_tier。
    conn.execute(
        "UPDATE photos SET auto_tier = ?, tier = ? WHERE id = ?",
        (auto_tier, auto_tier, photo_id),
    )
    conn.commit()


def set_analysis(conn, photo_id, auto_tier, phash=None, focus_score=None, keep_tier=False):
    """分析一趟写回：档位 + 感知哈希phash + 主体锐度分focus_score(供堆叠选封面/排序/分组)。
    keep_tier=True：只更 auto_tier/phash/focus_score，**保留用户手动改过的 tier**(重评旧数据时用)；
    否则 tier 跟随 auto_tier(新分析、或重评未被手动覆盖的)。"""
    if keep_tier:
        conn.execute(
            "UPDATE photos SET auto_tier = ?, phash = ?, focus_score = ? WHERE id = ?",
            (auto_tier, phash, focus_score, photo_id),
        )
    else:
        conn.execute(
            "UPDATE photos SET auto_tier = ?, tier = ?, phash = ?, focus_score = ? WHERE id = ?",
            (auto_tier, auto_tier, phash, focus_score, photo_id),
        )
    conn.commit()


def set_analysis_auto(conn, photo_id, auto_tier, phash=None, focus_score=None, score_ver=None):
    """分析写回，"用户是否手动改过档"在同一条 UPDATE 里按**当前**行判定：tier 为空或仍等于旧
    auto_tier(用户没动过)才跟随新判定，否则保留用户的档。SET 里的表达式都读更新前的旧值。
    比"开局拍快照再判断"安全：分析途中用户刚手动改的档不会被覆盖。返回写入后的实际 tier。
    score_ver：记下这次是用第几版算法评的(算法升级后据此重评)。"""
    conn.execute(
        "UPDATE photos SET tier = CASE WHEN tier IS NULL OR tier = auto_tier THEN ? ELSE tier END, "
        "auto_tier = ?, phash = ?, focus_score = ?, score_ver = COALESCE(?, score_ver) WHERE id = ?",
        (auto_tier, auto_tier, phash, focus_score, score_ver, photo_id),
    )
    conn.commit()
    row = conn.execute("SELECT tier FROM photos WHERE id = ?", (photo_id,)).fetchone()
    return row["tier"] if row else None


def get_tiers(conn, photo_ids):
    """{id: 当前 tier}——推给前端的档位以推送那一刻的库为准。"""
    ids = list(photo_ids or [])
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    return {r["id"]: r["tier"] for r in
            conn.execute(f"SELECT id, tier FROM photos WHERE id IN ({placeholders})", ids)}


def set_phash(conn, photo_id, phash):
    """只写感知哈希(不碰 tier/focus_score)。给"已分析过但加 phash 列之前入库、phash 为空"
    的老照片补算用——不能覆盖用户已有的档位判定。"""
    conn.execute("UPDATE photos SET phash = ? WHERE id = ?", (phash, photo_id))
    conn.commit()


def list_missing_phash(conn):
    """还没算感知哈希的照片(id/path)——补算堆叠分组所需的 phash 用。"""
    cur = conn.execute("SELECT id, path FROM photos WHERE phash IS NULL")
    return cur.fetchall()


def list_for_grouping(conn):
    """取堆叠分组要的字段(只含已算出 phash 的，即分析过的)：id/拍摄时间/机型/phash/锐度分。"""
    cur = conn.execute(
        "SELECT id, path, capture_time, cam, phash, focus_score FROM photos "
        "WHERE phash IS NOT NULL ORDER BY id"
    )
    return cur.fetchall()


_NEEDS_ANALYSIS = "tier IS NULL OR phash IS NULL OR COALESCE(score_ver, 0) < ?"


def list_needs_analysis(conn, score_ver=0):
    """需要(重新)分析的照片：从未分析(tier IS NULL)、缺感知哈希(phash IS NULL，旧数据)、
    或是用旧版评分算法评的(score_ver 低于当前版本)。
    带 tier/auto_tier 供判断用户是否手动改过档(tier!=auto_tier=手动改过，重评时保留)。
    旧数据靠"缺phash"/"旧版本"被纳入 → 点一次"分析"就能补phash(出堆叠)+用新模型重评。"""
    cur = conn.execute(
        f"SELECT id, path, iso, cam, tier, auto_tier FROM photos WHERE {_NEEDS_ANALYSIS}", (score_ver,)
    )
    return cur.fetchall()


def needs_analysis_count(conn, score_ver=0):
    row = conn.execute(
        f"SELECT COUNT(*) AS c FROM photos WHERE {_NEEDS_ANALYSIS}", (score_ver,)
    ).fetchone()
    return row["c"]


def list_unanalyzed(conn):
    # 只取还没定档的（tier IS NULL）：已手动改判或已分析过的都跳过，避免重复算、
    # 避免覆盖用户改判。带 path(评分要读缓存文件/原文件，数据库不再存图像字节)
    # 和 iso(噪点自适应)。
    cur = conn.execute("SELECT id, path, iso FROM photos WHERE tier IS NULL")
    return cur.fetchall()


def path_exists(conn, path):
    """这条路径是否已在库里。用于重新导入同一张卡时跳过已导入的照片，
    既让"新导入张数"计数准确，也省掉对已有照片重复解码缩略图/读EXIF的开销。"""
    row = conn.execute("SELECT 1 FROM photos WHERE path = ? LIMIT 1", (str(path),)).fetchone()
    return row is not None


def get_ids_for_folder(conn, folder):
    cur = conn.execute("SELECT id FROM photos WHERE folder = ? ORDER BY id", (folder,))
    return [row["id"] for row in cur.fetchall()]


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
    # 侧边栏只列"来自SD卡"的文件夹(is_card=1)——用户要的"只记SD卡、不记本地"。
    # 本地磁盘导入的照片仍在库里、仍显示在"全部文件夹"/时间视图，只是不给侧边栏快捷入口。
    # 带上 card_serial(组内一致，同一文件夹属同一张卡)供 api 层做"是不是当前这张卡"的实时判定。
    cur = conn.execute(
        "SELECT folder, COUNT(*) AS count, MAX(card_serial) AS card_serial FROM photos WHERE is_card = 1 "
        "GROUP BY folder ORDER BY MAX(id) DESC"
    )
    return [{"folder": row["folder"], "count": row["count"], "card_serial": row["card_serial"]}
            for row in cur.fetchall()]


def list_local_folders(conn):
    # 本地(非SD卡, is_card=0)导入的文件夹。这些**不进SD卡记忆**(插卡不自动加载)，但用户要求
    # 导入后也在侧边栏显示(当前会话看得见)。由 api 层再按"文件夹当前是否还存在"过滤。
    cur = conn.execute(
        "SELECT folder, COUNT(*) AS count FROM photos WHERE is_card = 0 "
        "GROUP BY folder ORDER BY MAX(id) DESC"
    )
    return [{"folder": row["folder"], "count": row["count"]} for row in cur.fetchall()]


def folders_for_serial(conn, card_serial):
    """这张卡(按卷序列号)记忆里导入过哪些文件夹——用来判断插卡时扫到的文件夹是不是"新的"。"""
    if not card_serial:
        return set()
    cur = conn.execute(
        "SELECT DISTINCT folder FROM photos WHERE card_serial = ?", (card_serial,)
    )
    return {row["folder"] for row in cur.fetchall()}


def rebind_card_paths(conn, card_serial, new_drive):
    """同一张卡再次插入可能换了盘符(E:→F:)，存库的绝对路径就失效了。把这张卡(按序列号)
    所有照片的 path/folder 盘符换成当前盘符 new_drive(形如 'F:')，之后所有读路径(缩略图
    重生成/存在性/逐张查看)统一用持久化路径即可，不必到处临时重建。
    用 UPDATE OR IGNORE：极少数情况新路径已被别的记录占用(UNIQUE(path))就跳过那一行、
    不崩溃。返回 (rebound, skipped) 计数。"""
    if not card_serial:
        return (0, 0)
    new_drive = os.path.splitdrive(new_drive)[0] or new_drive  # 归一成 'F:'，容忍传 'F:\\'
    rows = conn.execute(
        "SELECT id, path, folder FROM photos WHERE card_serial = ?", (card_serial,)
    ).fetchall()
    rebound = skipped = 0
    for row in rows:
        new_path = new_drive + os.path.splitdrive(row["path"])[1]
        new_folder = new_drive + os.path.splitdrive(row["folder"])[1]
        if new_path == row["path"] and new_folder == row["folder"]:
            continue  # 盘符没变，无需改
        before = conn.total_changes
        conn.execute(
            "UPDATE OR IGNORE photos SET path = ?, folder = ? WHERE id = ?",
            (new_path, new_folder, row["id"]),
        )
        if conn.total_changes > before:
            rebound += 1
        else:
            skipped += 1  # UNIQUE(path) 撞车被 IGNORE，留旧路径
    conn.commit()
    return (rebound, skipped)
