"""RAW 传感器层面曝光/噪点测量的契约测试：用合成的拜耳马赛克(已知噪声曲线、已知饱和区域)验证。"""
import numpy as np

from shiguang import raw_analysis as ra

BLACK = 600
WHITE = 15892          # RawSpeed 里 Z50II 14bit 的白电平
DESC = b"RGBG"


def _colors(h, w):
    tile = np.array([[0, 1], [3, 2]])   # RGGB
    return np.tile(tile, (h // 2, w // 2))


def _scene(h, w):
    """平滑的场景亮度(减黑电平后的 DN)：从暗到亮的渐变 + 几个柔和的光斑。"""
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    base = 30 + 7000 * (x / w) ** 2 + 1500 * (y / h)
    for cy, cx, r, amp in ((0.3, 0.3, 60, 2500), (0.7, 0.6, 90, -800), (0.5, 0.85, 50, 3000)):
        base += amp * np.exp(-((y - cy * h) ** 2 + (x - cx * w) ** 2) / (2 * r * r))
    return np.clip(base, 5, None)


def _mosaic(scene, a=1.6, b=36.0, gains=(0.6, 1.0, 0.5, 1.0), seed=1, clip=True):
    """按 σ² = a·μ + b 加泊松-高斯近似噪声，再加黑电平、按白电平截顶。"""
    rng = np.random.default_rng(seed)
    h, w = scene.shape
    colors = _colors(h, w)
    gain = np.array(gains)[colors]
    mu = scene * gain
    noisy = mu + rng.normal(0, 1, mu.shape) * np.sqrt(a * mu + b)
    raw = noisy + BLACK
    if clip:
        raw = np.minimum(raw, WHITE)
    return np.clip(raw, 0, 65535).astype(np.uint16), colors


def _true_snr(mu, a=1.6, b=36.0):
    return 20 * np.log10(mu / np.sqrt(a * mu + b))


def test_noise_curve_recovers_known_snr():
    """在已知噪声曲线的合成 RAW 上，18% 灰处的信噪比估计误差 < 1 dB。"""
    scene = _scene(800, 1200)
    raw, colors = _mosaic(scene)
    out = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC)
    truth = _true_snr(0.18 * (WHITE - BLACK))
    assert abs(out["snr18_db"] - truth) < 1.0


def test_noise_estimate_robust_to_texture():
    """画面里有大量边缘/纹理时，噪声估计也不被纹理抬高(取低分位 + 双绿差分)。"""
    scene = _scene(800, 1200)
    yy, xx = np.mgrid[0:800, 0:1200]
    scene = scene + 900 * (((yy // 9) + (xx // 9)) % 2)   # 9 像素周期的棋盘：大量强边缘
    raw, colors = _mosaic(scene)
    out = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC)
    truth = _true_snr(0.18 * (WHITE - BLACK))
    # 极端情况(每一块都布满硬边缘)：误差 < 2.5 dB，且只会偏保守(估得更"噪")。用方差估时误差是 12 dB
    assert abs(out["snr18_db"] - truth) < 2.5


def test_noisier_sensor_gives_lower_snr():
    scene = _scene(600, 900)
    clean = ra.analyze_mosaic(*_mosaic(scene, a=0.8, b=10), [BLACK] * 4, WHITE, color_desc=DESC)
    noisy = ra.analyze_mosaic(*_mosaic(scene, a=12, b=900), [BLACK] * 4, WHITE, color_desc=DESC)
    assert noisy["snr18_db"] < clean["snr18_db"] - 8


def test_scene_snr_reflects_underexposure():
    """同一传感器，欠曝(整体暗 3 档)的照片中间调信噪比明显更低——提亮后噪点不会变少。"""
    scene = _scene(600, 900)
    normal = ra.analyze_mosaic(*_mosaic(scene), [BLACK] * 4, WHITE, color_desc=DESC)
    under = ra.analyze_mosaic(*_mosaic(scene / 8), [BLACK] * 4, WHITE, color_desc=DESC)
    assert under["snr_scene_db"] < normal["snr_scene_db"] - 6


def test_sensor_saturated_patch_counts_as_highlight_clipping():
    """一片区域四个通道都顶到白电平 → 全通道高光修剪，面积约等于这片区域。"""
    scene = _scene(600, 900)
    scene[:150, :300] = 60000             # 左上 1/12 远超白电平
    raw, colors = _mosaic(scene)
    out = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC)
    assert 6.5 < out["hl_clip_pct"] < 9.5
    assert out["shadow_pct"] < 1


def test_single_channel_saturation_is_color_clip_not_full_clip():
    """只有红通道饱和(红花/夕阳)：算颜色饱和(可部分恢复)，不算全通道修剪。"""
    scene = _scene(600, 900)
    scene[300:450, 300:600] = 20000      # 红增益 0.6 → 12000+... 让红饱和、绿蓝不饱和
    raw, colors = _mosaic(scene, gains=(1.0, 0.5, 0.3, 0.5))
    out = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC)
    assert out["hl_clip_pct"] < 0.5
    assert out["color_clip_pct"] > 5


def test_lower_saturation_plateau_is_detected():
    """绿色通道在标称白电平之前就饱和(某些机型如此)：按数据里的饱和平台判，不漏报。"""
    scene = _scene(600, 900)
    scene[:150, :300] = 60000
    raw, colors = _mosaic(scene)
    g = (colors == 1) | (colors == 3)
    raw = raw.copy()
    raw[g] = np.minimum(raw[g], 15500)    # 绿色在 15500 就到顶，标称白电平却是 16383
    out = ra.analyze_mosaic(raw, colors, [BLACK] * 4, 16383, color_desc=DESC)
    assert out["hl_clip_pct"] > 6


def test_deep_shadow_counts_as_shadow_clipping():
    scene = _scene(600, 900)
    scene[400:, :] = 5                     # 下方 1/3 几乎全黑(远低于饱和 8 档)
    raw, colors = _mosaic(scene, a=0.2, b=1)
    out = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC)
    assert out["shadow_pct"] > 25


def test_trust_check_accepts_matching_preview_and_rejects_garbage():
    """与内嵌 JPEG 明暗对得上才信 RAW；解坏的数据(一片噪声)直接不信——不会拿它判废。"""
    scene = _scene(600, 900)
    raw, colors = _mosaic(scene)
    jpeg = 255 * (scene / scene.max()) ** (1 / 2.2)            # 相机曲线：伽马
    good = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC, jpeg_lum=jpeg[::4, ::4])
    assert good["trusted"] and good["rot"] == 0
    rotated = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC, jpeg_lum=np.rot90(jpeg)[::4, ::4])
    assert rotated["trusted"] and rotated["rot"] == 1
    garbage = np.random.default_rng(3).integers(BLACK, WHITE, raw.shape).astype(np.uint16)
    bad = ra.analyze_mosaic(garbage, colors, [BLACK] * 4, WHITE, color_desc=DESC, jpeg_lum=jpeg[::4, ::4])
    assert not bad["trusted"]


def test_non_bayer_returns_none():
    raw = np.zeros((60, 60), np.uint16)
    xtrans = np.tile(np.arange(36).reshape(6, 6) % 3, (10, 10))
    assert ra.analyze_mosaic(raw, xtrans, [0] * 4, 16383, color_desc=b"RGBG") is None


def test_measure_raw_unreadable_file_returns_none(tmp_path):
    f = tmp_path / "x.nef"
    f.write_bytes(b"not a raw file")
    assert ra.measure_raw(f) is None


def test_invalid_white_level_returns_none():
    raw, colors = _mosaic(_scene(200, 300))
    assert ra.analyze_mosaic(raw, colors, [BLACK] * 4, BLACK, color_desc=DESC) is None


def test_trust_survives_jpeg_with_many_crushed_blacks():
    """夜景：JPEG 一大半格子压成纯黑，不该因此判 RAW 不可信。"""
    scene = _scene(600, 900)
    scene[:, :520] = 3
    raw, colors = _mosaic(scene, a=0.3, b=2)
    jpeg = np.where(scene < 100, 0.0, 255 * (scene / scene.max()) ** (1 / 2.2))
    out = ra.analyze_mosaic(raw, colors, [BLACK] * 4, WHITE, color_desc=DESC, jpeg_lum=jpeg[::4, ::4])
    assert out["trusted"]
