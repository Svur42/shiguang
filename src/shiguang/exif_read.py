import logging
import os
from pathlib import Path

import exifread

# exifread 对无EXIF文件会往日志打印提示，上千张存量补读时会刷屏，静音掉
logging.getLogger("exifread").setLevel(logging.CRITICAL)


def _normalize_capture_time(raw):
    """EXIF DateTimeOriginal 'YYYY:MM:DD HH:MM:SS' → 可排序的 'YYYY-MM-DD HH:MM:SS'。非法/空返回 None。"""
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    parts = raw.split(" ")
    if len(parts) != 2:
        return None
    date_part, time_part = parts
    date_bits = date_part.split(":")
    if len(date_bits) != 3 or not all(b.isdigit() for b in date_bits):
        return None
    y, m, d = date_bits
    if len(y) != 4:
        return None
    return f"{y}-{m}-{d} {time_part}"


def _format_day_time(capture_time):
    """'2024-06-14 09:12:03' → ('2024年6月14日', '09:12:03')。None → (None, None)。"""
    if not capture_time:
        return (None, None)
    try:
        date_part, time_part = capture_time.split(" ")
        y, m, d = date_part.split("-")
        day = f"{int(y)}年{int(m)}月{int(d)}日"
        return (day, time_part)
    except Exception:
        return (None, None)


def _human_size(num_bytes):
    if num_bytes is None:
        return None
    mb = num_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f}MB"
    kb = num_bytes / 1024
    return f"{kb:.1f}KB"


def _ratio_to_float(tag):
    try:
        v = tag.values[0]
        return float(v.num) / float(v.den)
    except Exception:
        try:
            return float(tag.values[0])
        except Exception:
            return None


def read_metadata(path):
    """从单个文件读 EXIF。返回固定字段集的 dict，读不到的字段为 None，绝不抛异常。
    支持 JPEG 和 TIFF 系 RAW（NEF/CR2/ARW/DNG/ORF）；CR3/HEIC 等读不到时字段为 None。"""
    path = Path(path)
    meta = {
        "capture_time": None,
        "iso": None,
        "shutter": None,
        "aperture": None,
        "focal": None,
        "cam": None,
        "size": None,
    }
    try:
        meta["size"] = _human_size(os.path.getsize(path))
    except OSError:
        pass

    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception:
        return meta

    dt = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
    meta["capture_time"] = _normalize_capture_time(str(dt)) if dt else None

    model = tags.get("Image Model")
    if model:
        meta["cam"] = str(model).strip()

    iso = tags.get("EXIF ISOSpeedRatings")
    if iso:
        try:
            meta["iso"] = int(str(iso.values[0]) if hasattr(iso, "values") else str(iso))
        except Exception:
            pass

    fn = tags.get("EXIF FNumber")
    fval = _ratio_to_float(fn) if fn else None
    if fval:
        meta["aperture"] = f"f/{fval:g}"

    et = tags.get("EXIF ExposureTime")
    if et:
        # str(ExposureTime) 对 1/400 曝光返回 "1/400"，对整秒返回 "2"，统一加 s 后缀
        meta["shutter"] = f"{et}s"

    fl = tags.get("EXIF FocalLength")
    flval = _ratio_to_float(fl) if fl else None
    if flval:
        meta["focal"] = f"{flval:g}mm"

    return meta
