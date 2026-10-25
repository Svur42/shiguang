import io

import numpy as np
from PIL import Image

from . import scoring

BINS = 64


def _load_rgb(image_bytes):
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def histograms(image_bytes):
    arr = np.asarray(_load_rgb(image_bytes), dtype=np.float64)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    def _hist(channel):
        counts, _ = np.histogram(channel, bins=BINS, range=(0, 255))
        return [int(c) for c in counts]

    return {"main": _hist(lum), "r": _hist(r), "g": _hist(g), "b": _hist(b)}


def _clip_masks_full(img):
    """详情面板用的死白/死黑 mask(与评分同一套判定，见 scoring.clip_masks)。

    判定在 512 长边上做(与评分口径一致、也快)，再放大回原尺寸、并与原尺寸的"真到顶/到底"
    像素取交集——边缘是逐像素精确的，不会一块一块。"""
    arr = np.asarray(img, dtype=np.uint8)
    h, w = arr.shape[:2]
    scale = scoring.PREP_LONG_EDGE / max(h, w)
    small = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR) if scale < 1 else img
    blown_s, crushed_s = scoring.clip_masks(np.asarray(small, dtype=np.uint8))

    def _up(m):
        if m.shape == (h, w):
            return m
        d = m.copy()   # 外扩一圈再放大，盖住小图上被"边缘有起伏"排除掉的那一圈
        d[1:] |= m[:-1]
        d[:-1] |= m[1:]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        up = Image.fromarray(d.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)
        return np.asarray(up) > 127

    blown = _up(blown_s) & (arr.min(axis=-1) >= scoring.T_HIGH)
    crushed = _up(crushed_s) & (arr.max(axis=-1) <= scoring.T_LOW)
    return arr, blown, crushed


def clipping(image_bytes):
    """死白/死黑占比(%)：只算成片、没有细节的部分(白衣服/白鸟/雪这类有纹理的白不算)。"""
    arr, blown, crushed = _clip_masks_full(_load_rgb(image_bytes))
    total = arr.shape[0] * arr.shape[1]
    return {
        "over_pct": round(float(blown.sum()) / total * 100, 1),
        "under_pct": round(float(crushed.sum()) / total * 100, 1),
    }


def make_overlay(image_bytes):
    """过曝/欠曝高亮图：红=死白(细节已丢)，蓝=死黑；其余压暗成灰底。"""
    img = _load_rgb(image_bytes)
    arr, over_mask, under_mask = _clip_masks_full(img)

    gray = np.asarray(img.convert("L")).astype(np.uint8)
    out = np.stack([gray, gray, gray], axis=-1)
    out = (out * 0.5).astype(np.uint8)

    out[over_mask] = [255, 40, 40]
    out[under_mask] = [50, 90, 255]

    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def make_overlay_from_masks(image_bytes, masks, rot=0):
    """用 RAW 实测的修剪区域画高亮图：红=全通道高光修剪(细节已丢)，琥珀=部分通道饱和(颜色饱和，
    可部分恢复)，蓝=阴影修剪。masks 是 RAW 单色平面尺寸的布尔图，rot=对齐预览需要逆时针转的 90° 次数。"""
    img = _load_rgb(image_bytes)
    w, h = img.size
    gray = np.asarray(img.convert("L")).astype(np.uint8)
    out = (np.stack([gray, gray, gray], axis=-1) * 0.5).astype(np.uint8)

    def fit(m):
        m = np.rot90(np.asarray(m, dtype=bool), rot)
        return np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) > 127

    out[fit(masks["shadow"])] = [50, 90, 255]
    out[fit(masks["color"])] = [255, 176, 32]
    out[fit(masks["hl"])] = [255, 40, 40]
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=85)
    return buf.getvalue()
