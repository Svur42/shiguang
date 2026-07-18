import io

import numpy as np
from PIL import Image

import shiguang.image_analysis as ia


def _img_bytes(color, size=(200, 100)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_histograms_shape_and_keys():
    h = ia.histograms(_img_bytes((128, 128, 128)))
    for key in ("main", "r", "g", "b"):
        assert key in h
        assert len(h[key]) == 64
        assert all(isinstance(v, (int, float)) for v in h[key])


def test_histograms_pure_gray_concentrated_in_middle():
    h = ia.histograms(_img_bytes((128, 128, 128)))
    main = h["main"]
    peak_bin = main.index(max(main))
    assert 24 <= peak_bin <= 40


def test_clipping_all_white_is_fully_overexposed():
    stats = ia.clipping(_img_bytes((255, 255, 255)))
    assert stats["over_pct"] > 95
    assert stats["under_pct"] < 5


def test_clipping_all_black_is_fully_underexposed():
    stats = ia.clipping(_img_bytes((0, 0, 0)))
    assert stats["under_pct"] > 95
    assert stats["over_pct"] < 5


def test_clipping_midtone_has_no_clipping():
    stats = ia.clipping(_img_bytes((128, 128, 128)))
    assert stats["over_pct"] < 1
    assert stats["under_pct"] < 1


def test_make_overlay_returns_jpeg_bytes():
    img = Image.new("RGB", (200, 100))
    px = img.load()
    for x in range(200):
        for y in range(100):
            px[x, y] = (255, 255, 255) if x < 100 else (0, 0, 0)
    buf = io.BytesIO(); img.save(buf, format="JPEG"); src = buf.getvalue()

    overlay = ia.make_overlay(src)

    out = Image.open(io.BytesIO(overlay))
    assert out.format == "JPEG"
    assert out.size == (200, 100)
