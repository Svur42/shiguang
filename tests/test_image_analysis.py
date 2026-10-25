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


def _png_bytes(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _big_textured_white(w=1200, h=800):
    yy, xx = np.mgrid[0:h, 0:w]
    tex = 244 + 10 * np.sin(xx / 1.9) * np.cos(yy / 2.7)
    return np.clip(np.stack([tex] * 3, axis=-1), 0, 255).astype(np.uint8)


def test_clipping_ignores_white_with_texture():
    """大图(详情面板用 2560 预览)上，白色但有纹理的区域不标红。"""
    clip = ia.clipping(_png_bytes(_big_textured_white()))
    assert clip["over_pct"] < 2


def test_clipping_counts_flat_blown_region_with_exact_edges():
    arr = _big_textured_white()
    arr[:200] = 255                       # 上方 1/4 平平一片死白
    clip = ia.clipping(_png_bytes(arr))
    assert 22 <= clip["over_pct"] <= 26
