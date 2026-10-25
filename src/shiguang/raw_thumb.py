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
    # 先缩后转色：thumbnail() 对 JPEG 会走 draft(DCT 域按 1/2~1/8 直接解出小图)，若先
    # convert 会逼着把相机内嵌的 6000px 级全图整张解码，单张慢 2~3 倍。小档(512)留
    # reducing_gap=2 保证画质(评分也读这一档)；大档(2560)用 1.0 才能吃到 1/2 缩放。
    gap = 2.0 if max_size <= 1024 else 1.0
    if img.mode in ("P", "PA", "1"):
        img = img.convert("RGB")   # 调色板/1-bit 先缩只能最近邻采样(锯齿)；这类图很小，先转色不费事
    try:
        img.thumbnail((max_size, max_size), reducing_gap=gap)
    except (OSError, ValueError):
        img = img.convert("RGB")   # 个别特殊模式(如16位)不支持先缩，退回先转色
        img.thumbnail((max_size, max_size))
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def downscale_jpeg(data, max_size):
    """把已有的缩略图(JPEG 字节)再缩小一档(网格小格子用的 256 档从 512 缩出)。"""
    return _resize_to_bytes(Image.open(io.BytesIO(data)), max_size)


def _passthrough_ok(img, max_size):
    """相机/文件里现成的 JPEG 能否原样给出：尺寸不超上限、没有 EXIF 方向标记(有的话浏览器会
    自动转，和预览/缩略图(不带 EXIF)方向对不上)、是普通的 RGB/灰度。"""
    try:
        orient = img.getexif().get(0x0112, 1)
    except Exception:
        return False
    if img.info.get("icc_profile"):
        return False   # 带色彩配置(AdobeRGB/P3)：预览/缩略图不带，原样给出的话放大换原图那一刻会色变
    return img.format == "JPEG" and max(img.size) <= max_size and orient in (None, 0, 1) and img.mode in ("RGB", "L")


def extract_full(path, max_size=6000):
    """解出接近原始分辨率的大图，供全屏放大到像素级"看原图/检查对焦"用。

    RAW 用相机内嵌的**全分辨率 JPEG 预览**(如尼康 NEF 内嵌 5568x3712，接近全画幅)，
    **不用 rawpy.postprocess 去马赛克**——老版 LibRaw(0.21)对新机型(如尼康 Z50 II)
    去马赛克会直接花屏("data corrupted")。内嵌 JPEG 是相机自己出的，颜色一定正确，
    分辨率也足够放大看对焦。JPG/PNG 直接用原图。上限 max_size 防超大图爆内存。

    能原样给就原样给(_passthrough_ok)：不解码、不重新压缩——画质就是相机写进去的那张，
    也省掉整张 2000 万像素解码+编码的几百毫秒。"""
    ext = Path(path).suffix.lower()
    if ext in RAW_EXTENSIONS:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()   # 内嵌预览，多为全分辨率JPEG
        if thumb.format == rawpy.ThumbFormat.JPEG:
            data = bytes(thumb.data)
            img = Image.open(io.BytesIO(data))
            if _passthrough_ok(img, max_size):
                return data
        else:
            img = Image.fromarray(thumb.data)
    elif ext in STANDARD_EXTENSIONS:
        img = Image.open(path)
        if ext in (".jpg", ".jpeg") and _passthrough_ok(img, max_size):
            return Path(path).read_bytes()
    else:
        raise ValueError(f"unsupported file type: {ext}")
    img = img.convert("RGB")
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
