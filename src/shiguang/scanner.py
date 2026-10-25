import contextlib
from pathlib import Path

from . import db
from . import exif_read
from . import raw_thumb

SUPPORTED_EXTENSIONS = raw_thumb.RAW_EXTENSIONS | raw_thumb.STANDARD_EXTENSIONS


def count_supported(folder_path):
    """统计一个文件夹里受支持的照片数量（供导入进度显示"共 N 张"用）。"""
    folder_path = Path(folder_path)
    try:
        return sum(1 for f in folder_path.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS)
    except OSError:
        return 0


def scan_folder(conn, folder_path, thumb_cache_dir=None, progress_callback=None, is_card=0,
                card_serial=None, db_lock=None):
    """扫描文件夹并导入照片。progress_callback(done, total) 在每处理完一张后调用一次，
    用于让调用方（比如界面）能显示"正在导入 X/Y 张"这种进度，而不是让用户干等。

    thumb_cache_dir 给了才写缩略图：缩略图不进数据库（数据库只存路径/标签/EXIF这些
    数据），直接写成 thumb_cache_dir/{id}.jpg 磁盘缓存文件，用 insert_photo 返回的
    id 命名。不传就只导入数据不生成缩略图（主要给测试用）。

    db_lock 给了就在每次 DB 调用时短暂持锁：导入时逐张解码图片(慢)不占锁，只有真正
    读写数据库的瞬间互斥——避免"整段导入(解码上千张)持锁"把插卡认卡/浏览都卡住。
    单连接跨线程(JS导入 vs watcher认卡)必须串行化 DB 访问。"""
    lock = db_lock if db_lock is not None else contextlib.nullcontext()
    folder_path = Path(folder_path)
    files = [f for f in sorted(folder_path.iterdir()) if f.suffix.lower() in SUPPORTED_EXTENSIONS]
    total = len(files)
    count = 0
    if thumb_cache_dir is not None:
        thumb_cache_dir = Path(thumb_cache_dir)
        thumb_cache_dir.mkdir(parents=True, exist_ok=True)
    for i, file_path in enumerate(files, start=1):
        # 已在库里的跳过：重新导入同一张卡时不重复解码/重复计数，count 只算真正新增的
        with lock:
            already = db.path_exists(conn, file_path)
        if already:
            if progress_callback:
                progress_callback(i, total)
            continue
        # 导入不再逐张解码缩略图(那是几千张要几分钟的元凶)——只读 EXIF(轻，读文件头标签)
        # + 建记录。缩略图改为**完全按需生成**：浏览到哪张，本地服务器再从原图现场生成那张
        # (ensure_cache_file)。导入因此从"逐张解码"降到"逐张读头+插库"，快一个数量级。
        # thumb_cache_dir 参数保留仅为兼容签名，不再在导入时写缓存。
        try:
            metadata = exif_read.read_metadata(file_path)
        except Exception:
            metadata = None
        with lock:
            photo_id = db.insert_photo(
                conn,
                path=file_path,
                folder=str(folder_path),
                filename=file_path.name,
                metadata=metadata,
                is_card=is_card,
                card_serial=card_serial,
            )
        count += 1
        if progress_callback:
            progress_callback(i, total)
    return count
