import io

import numpy as np
from PIL import Image

BINS = 64
OVER_THRESHOLD = 250
UNDER_THRESHOLD = 5


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


def clipping(image_bytes):
    arr = np.asarray(_load_rgb(image_bytes))
    total = arr.shape[0] * arr.shape[1]
    over = np.any(arr >= OVER_THRESHOLD, axis=-1).sum()
    under = np.all(arr <= UNDER_THRESHOLD, axis=-1).sum()
    return {
        "over_pct": round(float(over) / total * 100, 1),
        "under_pct": round(float(under) / total * 100, 1),
    }


def make_overlay(image_bytes):
    img = _load_rgb(image_bytes)
    arr = np.asarray(img).astype(np.uint8)
    over_mask = np.any(arr >= OVER_THRESHOLD, axis=-1)
    under_mask = np.all(arr <= UNDER_THRESHOLD, axis=-1)

    gray = np.asarray(img.convert("L")).astype(np.uint8)
    out = np.stack([gray, gray, gray], axis=-1)
    out = (out * 0.5).astype(np.uint8)

    out[over_mask] = [255, 40, 40]
    out[under_mask] = [50, 90, 255]

    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=85)
    return buf.getvalue()
