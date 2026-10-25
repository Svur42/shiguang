"""P0 评分模块的行为契约测试。

策略：用合成图片（清晰棋盘/模糊版/纯白/纯黑/带纹理的正常图）测极端与边界，
不依赖具体阈值的精确值（阈值是待校准量），只断言相对关系和硬伤判定。
"""
import io

import numpy as np
import pytest
from PIL import Image

from shiguang import scoring


def _to_jpeg(arr):
    """numpy uint8 (H,W,3) -> JPEG bytes。"""
    return _encode(arr, "JPEG")


def _to_png(arr):
    return _encode(arr, "PNG")


def _encode(arr, fmt):
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format=fmt)
    return buf.getvalue()


def _checkerboard(size=512, cell=8):
    """高频棋盘 = 极清晰（大 Laplacian 方差）。纯 0/255，仅用于清晰度相对测试。"""
    idx = (np.arange(size) // cell) % 2
    board = (idx[:, None] ^ idx[None, :]) * 255
    return np.stack([board] * 3, axis=-1).astype(np.uint8)


def _sharp_photo(size=512, cell=32, lo=60, hi=200):
    """锐利、曝光正常（中间调、不裁切）、边缘稀疏（不像噪点）的"正常好片"。"""
    idx = (np.arange(size) // cell) % 2
    board = np.where((idx[:, None] ^ idx[None, :]).astype(bool), hi, lo)
    return np.stack([board] * 3, axis=-1).astype(np.uint8)


def _blur(arr, passes=12):
    """反复 3x3 盒式模糊，把清晰图糊掉。"""
    a = arr.astype(np.float64)
    for _ in range(passes):
        a[1:-1, 1:-1] = (
            a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] + a[1:-1, 1:-1]
        ) / 5.0
    return a.astype(np.uint8)


def _textured_gradient(size=512):
    """有纹理、曝光正常的"正常好片"合成：渐变 + 细密条纹。"""
    y = np.linspace(40, 210, size)[:, None] * np.ones((1, size))
    stripes = 25 * np.sin(np.arange(size) / 2.0)[None, :]
    g = np.clip(y + stripes, 0, 255)
    return np.stack([g] * 3, axis=-1).astype(np.uint8)


# ── 单指标 ────────────────────────────────────────────────

def test_sharpness_sharp_much_greater_than_blurred():
    sharp = scoring.sharpness(scoring._prep(_to_png(_checkerboard()))[0])
    blurred = scoring.sharpness(scoring._prep(_to_png(_blur(_checkerboard())))[0])
    assert sharp["vol"] > blurred["vol"] * 5


def test_exposure_all_white_is_overexposed():
    white = np.full((256, 256, 3), 255, np.uint8)
    e = scoring.exposure(scoring._prep(_to_png(white))[1])
    assert e["over_pct"] > 90


def test_exposure_all_black_is_underexposed():
    black = np.zeros((256, 256, 3), np.uint8)
    e = scoring.exposure(scoring._prep(_to_png(black))[1])
    assert e["under_pct"] > 90


def test_exposure_channel_clip_catches_saturated_red():
    """高饱和红：R 通道爆但灰度不亮——分通道能抓、灰度会漏。"""
    red = np.zeros((256, 256, 3), np.uint8)
    red[..., 0] = 255
    e = scoring.exposure(scoring._prep(_to_png(red))[1])
    assert e["over_channel_pct"] > 90


def test_noise_sigma_noisy_greater_than_clean():
    rng = np.random.default_rng(0)
    base = _textured_gradient(256)
    noisy = np.clip(base.astype(np.float64) + rng.normal(0, 25, base.shape), 0, 255).astype(np.uint8)
    _, _, raw_clean = scoring._prep(_to_png(base))
    _, _, raw_noisy = scoring._prep(_to_png(noisy))
    sat = np.zeros(raw_clean.shape, bool)
    s_clean = scoring.noise_sigma(raw_clean, sat)
    s_noisy = scoring.noise_sigma(raw_noisy, sat)
    assert s_noisy > s_clean + 8


# ── 整体定档 ──────────────────────────────────────────────

def test_score_returns_tier_and_metrics():
    result = scoring.score_image_bytes(_to_jpeg(_textured_gradient()))
    assert result["tier"] in ("bad", "fix", "good")
    assert "metrics" in result
    for k in ("vol", "ten", "over_pct", "under_pct", "sigma"):
        assert k in result["metrics"]


def test_score_heavily_blurred_is_bad():
    result = scoring.score_image_bytes(_to_jpeg(_blur(_sharp_photo(), passes=20)))
    assert result["tier"] == "bad"


def test_score_overexposed_is_bad():
    white = np.full((512, 512, 3), 255, np.uint8)
    result = scoring.score_image_bytes(_to_jpeg(white))
    assert result["tier"] == "bad"


def test_score_clean_sharp_photo_is_not_bad():
    """有纹理、清晰、曝光正常的图不该被判废。"""
    result = scoring.score_image_bytes(_to_jpeg(_sharp_photo()))
    assert result["tier"] != "bad"


def test_score_mildly_soft_is_fix_not_bad():
    """稍软的片进"可修"给人看，不被清晰度一票压成废——调研头号教训。"""
    result = scoring.score_image_bytes(_to_jpeg(_blur(_sharp_photo(), passes=4)))
    assert result["tier"] == "fix"


def test_score_partial_overexposure_is_fix_not_bad():
    """局部小面积过曝(远低于死白硬阈)是可修，不硬废。"""
    arr = _sharp_photo().astype(np.float64)
    arr[:int(512 * 0.05)] = 255      # 顶部 5% 死白
    result = scoring.score_image_bytes(_to_jpeg(arr))
    assert result["tier"] in ("fix", "good")   # 不得为 bad（小面积死白可修）
    assert result["tier"] != "bad"


def test_score_saturated_color_is_not_bad():
    """锐利 + 大面积单通道爆(红花/霓虹/夕阳)绝不能判废——调研头号误杀。
    单通道爆是丢色彩细节可修，亮度没死白，不该走一票否决。"""
    red = _sharp_photo(lo=60, hi=200).astype(np.float64)
    red[..., 0] = 255            # R 通道整幅爆(灰度不亮，over_pct≈0)
    red[..., 1] = np.clip(red[..., 1], 0, 200)
    red[..., 2] = np.clip(red[..., 2], 0, 200)
    result = scoring.score_image_bytes(_to_jpeg(red))
    assert result["metrics"]["over_channel_pct"] > 90      # 确实大面积单通道爆
    assert result["metrics"]["over_pct"] < 20              # 但亮度没死白
    assert result["tier"] != "bad"


def _sharp_subject_on_soft_bg(size=512, patch=160):
    """浅景深合成：软背景(有纹理但不锐)+ 画面中心一块针尖锐的细棋盘 = 被对焦的主体。
    模拟拍鸟/微距——主体锐、背景虚化。"""
    rng = np.random.default_rng(3)
    bg = rng.normal(128, 40, (size, size))
    for _ in range(6):        # 盒式模糊把噪声磨成"有纹理但低锐"的软背景(std仍>阈, VoL低)
        bg[1:-1, 1:-1] = (bg[:-2, 1:-1] + bg[2:, 1:-1] + bg[1:-1, :-2] + bg[1:-1, 2:] + bg[1:-1, 1:-1]) / 5.0
    arr = np.stack([np.clip(bg, 30, 225)] * 3, axis=-1)
    c0 = (size - patch) // 2
    idx = (np.arange(patch) // 4) % 2
    board = (idx[:, None] ^ idx[None, :]) * 140 + 60      # 60..200 中间调，避免过曝干扰
    arr[c0:c0 + patch, c0:c0 + patch] = np.stack([board] * 3, axis=-1)
    return arr.astype(np.uint8)


def test_metrics_expose_focus_fields():
    m = scoring.score_image_bytes(_to_jpeg(_sharp_photo()))["metrics"]
    for k in ("subject_vol", "focus_ratio", "focus_locality", "subject_center"):
        assert k in m


def test_focus_detects_locked_subject_on_soft_background():
    """锐主体+软背景：主体明显锐于背景(ratio高)、锐块聚成一簇(locality高)、质心在中央，
    且不被判废——方案①要救的正是这种浅景深精选片。"""
    m = scoring.score_image_bytes(_to_jpeg(_sharp_subject_on_soft_bg()))
    met = m["metrics"]
    assert met["focus_ratio"] > scoring.FOCUS_RATIO_MIN         # 主体远锐于背景
    assert met["focus_locality"] >= scoring.FOCUS_LOCALITY_MIN  # 锐块聚成一个主体
    assert met["subject_center"] is not None
    y, x = met["subject_center"]
    assert 0.3 < y < 0.7 and 0.3 < x < 0.7                       # 对焦点落在画面中央(主体处)
    assert m["tier"] != "bad"


def _soft_photo_with_corner_stamp(size=512):
    """整体偏软的片 + 角落一小块高对比"日期戳/水印"式细纹(单块)。
    这类假主体不该被当'对焦锁定'把软片错托成精选(reviewer 抓的误托场景)。"""
    base = _blur(_sharp_photo(), passes=5).astype(np.float64)
    s = 40
    idx = (np.arange(s) // 2) % 2
    stamp = (idx[:, None] ^ idx[None, :]) * 180 + 30
    base[size - s:, size - s:] = np.stack([stamp] * 3, axis=-1)
    return base.astype(np.uint8)


def test_corner_stamp_does_not_rescue_soft_photo_to_good():
    """软片角落的日期戳/水印(单块/一条)不满足'主体够大且成团'，不触发托底，不被抬成精选。"""
    m = scoring.score_image_bytes(_to_jpeg(_soft_photo_with_corner_stamp()))
    assert m["metrics"]["focus_blocks"] < scoring.FOCUS_MIN_BLOCKS or m["metrics"].get("focus_span", 0) < 2
    assert m["tier"] != "good"


def test_uniform_soft_does_not_trigger_subject_lock():
    """整幅均匀轻糊：主体与背景无锐度分离(ratio≈1)，不该被误判成'对焦锁定'而错托成精选。
    这条守住 test_score_mildly_soft_is_fix_not_bad 不被新逻辑破坏。"""
    m = scoring.score_image_bytes(_to_jpeg(_blur(_sharp_photo(), passes=4)))
    assert m["metrics"]["focus_ratio"] < scoring.FOCUS_RATIO_MIN


def test_score_accepts_iso_hint_without_crashing():
    result = scoring.score_image_bytes(_to_jpeg(_textured_gradient()), iso=6400)
    assert result["tier"] in ("bad", "fix", "good")
