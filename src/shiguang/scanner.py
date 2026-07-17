from pathlib import Path

from . import db
from . import raw_thumb

SUPPORTED_EXTENSIONS = raw_thumb.RAW_EXTENSIONS | raw_thumb.STANDARD_EXTENSIONS


def scan_folder(conn, folder_path):
    folder_path = Path(folder_path)
    count = 0
    for file_path in sorted(folder_path.iterdir()):
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            thumbnail = raw_thumb.extract_thumbnail(file_path)
        except Exception:
            thumbnail = None
        db.insert_photo(
            conn,
            path=file_path,
            folder=str(folder_path),
            filename=file_path.name,
            thumbnail=thumbnail,
        )
        count += 1
    return count
