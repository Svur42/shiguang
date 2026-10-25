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


def extract_full(path, max_size=6000):
    """解出接近原始分辨率的大图，供全屏放大到像素级"看原图/检查对焦"用。

    RAW 用相机内嵌的**全分辨率 JPEG 预览**(如尼康 NEF 内嵌 5568x3712，接近全画幅)，
    **不用 rawpy.postprocess 去马赛克**——老版 LibRaw(0.21)对新机型(如尼康 Z50 II)
    去马赛克会直接花屏("data corrupted")。内嵌 JPEG 是相机自己出的，颜色一定正确，
    分辨率也足够放大看对焦。JPG/PNG 直接用原图。上限 max_size 防超大图爆内存。"""
    ext = Path(path).suffix.lower()
    if ext in RAW_EXTENSIONS:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()   # 内嵌预览，多为全分辨率JPEG
        if thumb.format == rawpy.ThumbFormat.JPEG:
            img = Image.open(io.BytesIO(thumb.data))
        else:
            img = Image.fromarray(thumb.data)
    elif ext in STANDARD_EXTENSIONS:
        img = Image.open(path)
    else:
        raise ValueError(f"unsupported file type: {ext}")
    img = img.convert("RGB")
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
