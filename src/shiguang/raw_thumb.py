import io
from pathlib import Path

import rawpy
from PIL import Image

RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".dng", ".raf"}
STANDARD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}


def extract_thumbnail(path, max_size=512):
    ext = Path(path).suffix.lower()
    if ext in RAW_EXTENSIONS:
        return _extract_raw_thumbnail(path, max_size)
    if ext in STANDARD_EXTENSIONS:
        return _extract_standard_thumbnail(path, max_size)
    raise ValueError(f"unsupported file type: {ext}")


def _extract_raw_thumbnail(path, max_size):
    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
    if thumb.format == rawpy.ThumbFormat.JPEG:
        img = Image.open(io.BytesIO(thumb.data))
    else:
        img = Image.fromarray(thumb.data)
    return _resize_to_bytes(img, max_size)


def _extract_standard_thumbnail(path, max_size):
    img = Image.open(path)
    return _resize_to_bytes(img, max_size)


def _resize_to_bytes(img, max_size):
    img = img.convert("RGB")
    img.thumbnail((max_size, max_size))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
