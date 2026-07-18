from pathlib import Path

from . import db
from . import exif_read
from . import raw_thumb

SUPPORTED_EXTENSIONS = raw_thumb.RAW_EXTENSIONS | raw_thumb.STANDARD_EXTENSIONS


def scan_folder(conn, folder_path, progress_callback=None):
    """扫描文件夹并导入照片。progress_callback(done, total) 在每处理完一张后调用一次，
    用于让调用方（比如界面）能显示"正在导入 X/Y 张"这种进度，而不是让用户干等。"""
    folder_path = Path(folder_path)
    files = [f for f in sorted(folder_path.iterdir()) if f.suffix.lower() in SUPPORTED_EXTENSIONS]
    total = len(files)
    count = 0
    for i, file_path in enumerate(files, start=1):
        try:
            thumbnail = raw_thumb.extract_thumbnail(file_path)
        except Exception:
            thumbnail = None
        try:
            metadata = exif_read.read_metadata(file_path)
        except Exception:
            metadata = None
        db.insert_photo(
            conn,
            path=file_path,
            folder=str(folder_path),
            filename=file_path.name,
            thumbnail=thumbnail,
            metadata=metadata,
        )
        count += 1
        if progress_callback:
            progress_callback(i, total)
    return count
