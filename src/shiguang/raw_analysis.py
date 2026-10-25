"""RAW 传感器数据层面的曝光与噪点测量(2026-10)。

为什么要看 RAW：相机内嵌的 JPEG 套了照片风格曲线，"白到顶"比传感器真饱和早 1~2 档——JPEG 上看着
大片过曝，RAW 里往往只有零点几的像素真饱和，转换时完全拉得回来(FastRawViewer 的对比案例)；机内
降噪又会把 JPEG 里的噪点抹掉。所以"细节是不是真丢了""噪点是不是真重"都得在 RAW 原始数据上量。

做法与依据(调研出处见 docs/superpowers/plans/2026-10-25-shiguang-ux-overhaul-and-next.md)：
- 高光修剪：按 CFA 逐通道，与该通道的饱和电平比(darktable 的 rawoverexposed 模块同思路)。饱和电平
  先取相机标称白电平，再看数据里是否有更低的"饱和平台"(有的机型绿色通道达不到标称白电平就饱和，
  LibRaw 论坛/lightcraft#759 记录过)。四个通道都饱和 = 全通道修剪(颜色和亮度都没了，高光重建也救不
  回)；只有部分通道饱和 = 颜色饱和(可部分恢复)。
- 阴影修剪：四个通道都低于饱和电平 8 档(高 ISO 放宽到 6.5 档)——FastRawViewer 的欠曝默认阈值，
  低于这里基本只剩噪声、没有可用细节。
- 修剪面积按"成片"计：零散的高光点/反光不算(scoring._keep_patches)。
- 噪点：传感器噪声是"泊松-高斯"、随亮度变化(Foi 2008)，所以不报一个单一 σ，而是拟合噪声曲线
  σ² = a·μ + b，再报信噪比(dB)。估计用同一个拜耳单元里两个绿色像素之差(Gr−Gb)/√2：两个相邻像素
  看到的画面几乎一样，相减后剩下的基本只有噪声；每 32×32 块算一次，同一亮度档里取方差偏小的那部分
  (纹理/边缘会把方差抬高，取低分位剔除)。
  · SNR18：18% 灰处的信噪比(DxOMark 的口径，反映 ISO 带来的噪点水平)；
  · 画面中间调信噪比：在这张照片亮度中位数处的信噪比——欠曝后再提亮，噪点不会变少，所以判"噪点
    重不重"看它。
- 可信度校验：把 RAW 缩成小图，与相机内嵌 JPEG 比秩相关。新机型/特殊压缩格式(比如尼康 Z50II 的
  "高效率"NEF，当前的 LibRaw 解不对)解出来是一片噪声，相关性会很低——这时一律不用 RAW 结果，
  退回用预览图估算，绝不拿解坏的数据判废片。
"""
import numpy as np

from . import scoring

CLIP_FRACTION = 0.98        # 达到饱和电平的 98% 即视为修剪(留 2% 吸收白电平标定误差)
SHADOW_EV = 8.0             # 低于饱和 8 档 = 暗部无有效数据(FastRawViewer 默认)
SHADOW_EV_HIGH_ISO = 6.5    # 高 ISO 时 FastRawViewer 建议 6~7 档
HIGH_ISO = 3200
NOISE_BLOCK = 32            # 噪声估计的分块边长(单个颜色平面上的像素)
NOISE_BIN_PCT = 20          # 同一亮度档里取方差的第 20 百分位(剔除纹理/边缘抬高的块)
TRUST_MIN_R = 0.8           # RAW 小图与内嵌 JPEG 的秩相关低于此 → 认为 RAW 没解对，不用
GRID = (32, 48)             # 可信度校验用的小图尺寸(行, 列)


def _bayer_layout(colors, color_desc):
    """从 raw_colors_visible 推出 2×2 拜耳排布：返回 {位置(dy,dx): (通道下标, 字母)}；非拜耳返回 None。"""
    if colors.shape[0] < 4 or colors.shape[1] < 4:
        return None
    tile = colors[:2, :2]
    if not np.array_equal(colors[2:4, 2:4], tile) or len(set(tile.ravel().tolist())) != 4:
        return None   # X-Trans 等非 2×2 排布，或单色传感器
    desc = color_desc.decode() if isinstance(color_desc, (bytes, bytearray)) else str(color_desc or "RGBG")
    layout = {}
    for dy in range(2):
        for dx in range(2):
            c = int(tile[dy, dx])
            layout[(dy, dx)] = (c, desc[c] if c < len(desc) else "?")
    letters = sorted(v[1] for v in layout.values())
    if letters != ["B", "G", "G", "R"]:
        return None
    return layout


def _saturation(plane, nominal):
    """该通道的实际饱和电平：数据里有明显的"饱和平台"且低于标称值，就用平台值。"""
    m = float(plane.max())
    if m < nominal * 0.995 and np.count_nonzero(plane >= m - 1) >= max(64, int(plane.size * 2e-5)):
        return m
    return nominal


def _noise_curve(g1, g2, clipped):
    """σ² = a·μ + b 的拟合(μ、σ 都以减去黑电平后的 DN 计)。拟合不出来返回 None。"""
    B = NOISE_BLOCK
    h, w = (g1.shape[0] // B) * B, (g1.shape[1] // B) * B
    if h < B or w < B:
        return None
    d = ((g1[:h, :w] - g2[:h, :w]) / np.sqrt(2)).reshape(h // B, B, w // B, B)
    m = ((g1[:h, :w] + g2[:h, :w]) / 2).reshape(h // B, B, w // B, B)
    clip_blocks = clipped[:h, :w].reshape(h // B, B, w // B, B).any(axis=(1, 3))
    mu = m.mean(axis=(1, 3))
    # 块内用中位数绝对偏差(MAD×1.4826)估 σ：边缘处两个绿像素看到的东西不同，差值会很大，但这类像素
    # 只占一小部分，中位数不受影响(50% 崩溃点)；用方差的话，满是枝叶的照片会把噪声估高好几倍。
    # 减中位数而不是零：两个绿通道增益略有差别也不影响。
    dd = d.transpose(0, 2, 1, 3).reshape(h // B, w // B, B * B)
    med = np.median(dd, axis=2, keepdims=True)
    var = (1.4826 * np.median(np.abs(dd - med), axis=2)) ** 2
    ok = ~clip_blocks & (mu > 0)
    mu, var = mu[ok], var[ok]
    if mu.size < 8:
        return None
    hi = float(np.percentile(mu, 99.5))
    lo = max(1.0, hi / 3000.0)
    edges = np.geomspace(lo, hi, 25)
    xs, ys = [], []
    for k in range(len(edges) - 1):
        sel = (mu >= edges[k]) & (mu < edges[k + 1])
        if np.count_nonzero(sel) >= 6:
            xs.append(float(np.median(mu[sel])))
            ys.append(float(np.percentile(var[sel], NOISE_BIN_PCT)))
    if not xs:
        return None
    xs, ys = np.array(xs), np.array(ys)
    if len(xs) == 1:
        return max(ys[0] / xs[0], 0.0), 0.0
    a, b = np.linalg.lstsq(np.stack([xs, np.ones_like(xs)], axis=1), ys, rcond=None)[0]
    if a < 0:
        a, b = 0.0, float(np.mean(ys))
    if b < 0:
        a, b = float(np.sum(xs * ys) / np.sum(xs * xs)), 0.0
    return float(a), float(b)


def _snr_db(mu, curve):
    a, b = curve
    var = a * mu + b
    if mu <= 0 or var <= 0:
        return None
    return float(20 * np.log10(mu / np.sqrt(var)))


def _grid(img, shape=GRID):
    """按块平均缩成小图(行, 列)。向量化(reduceat)，图再大也只是几次 numpy 调用。"""
    gh, gw = shape
    img = np.asarray(img, dtype=np.float64)
    h, w = img.shape
    if h < gh or w < gw:   # 比网格还小：先放大到够分
        img = np.repeat(np.repeat(img, -(-gh // h), axis=0), -(-gw // w), axis=1)
        h, w = img.shape
    ys = np.linspace(0, h, gh + 1).astype(int)[:-1]
    xs = np.linspace(0, w, gw + 1).astype(int)[:-1]
    sums = np.add.reduceat(np.add.reduceat(img, ys, axis=0), xs, axis=1)
    cnt_y = np.diff(np.append(ys, h))[:, None]
    cnt_x = np.diff(np.append(xs, w))[None, :]
    return sums / (cnt_y * cnt_x)


def _avg_rank(x):
    """平均秩(并列值取平均)。"""
    x = x.ravel()
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ranks = np.empty(len(x), np.float64)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return ranks


def _rank_corr(a, b):
    """秩相关(Spearman)：只看明暗顺序，相机的色调曲线/伽马不影响。JPEG 里压成纯黑/纯白的格子
    (夜景、剪影)排不出先后，剔除后再算，免得无谓拉低相关性。"""
    a, b = a.ravel(), b.ravel()
    keep = (b > 1.0) & (b < 254.0)
    if keep.sum() >= 24:
        a, b = a[keep], b[keep]
    ra, rb = _avg_rank(a), _avg_rank(b)
    ra -= ra.mean()
    rb -= rb.mean()
    den = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / den) if den > 0 else 0.0


def consistency(raw_lum, jpeg_lum):
    """RAW 亮度图与 JPEG 亮度图对得上吗：返回 (最大秩相关, 让 RAW 对齐 JPEG 需要逆时针转的 90° 次数)。
    JPEG 可能是竖拍转正过的，所以四个方向都试。"""
    best = (-1.0, 0)
    raw_lum = np.asarray(raw_lum)
    jg = _grid(jpeg_lum)
    land = _grid(raw_lum, GRID)                    # 横着放时的小图
    port = _grid(raw_lum, (GRID[1], GRID[0]))       # 竖着放时(转 90° 后)的小图
    for k in range(4):
        small = np.rot90(land if k % 2 == 0 else port, k)
        if small.shape != jg.shape:
            continue
        r_img = np.rot90(raw_lum, k)
        if (r_img.shape[0] > r_img.shape[1]) != (jpeg_lum.shape[0] > jpeg_lum.shape[1]):
            continue
        r = _rank_corr(small, jg)
        if r > best[0]:
            best = (r, k)
    return best


def analyze_mosaic(raw, colors, black, white_level, white_per_channel=None, color_desc=b"RGBG",
                   iso=None, jpeg_lum=None, want_masks=False):
    """对 RAW 马赛克数据做曝光/噪点测量(纯 numpy，便于用合成数据测试)。

    raw: (H,W) 可见区原始值；colors: (H,W) 每个像素的颜色通道下标；black: 4 个通道的黑电平；
    jpeg_lum: 内嵌 JPEG 的亮度(任意尺寸，用于可信度校验)。不是拜耳排布返回 None。"""
    layout = _bayer_layout(np.asarray(colors), color_desc)
    if layout is None:
        return None
    raw = np.asarray(raw)
    h, w = (raw.shape[0] // 2) * 2, (raw.shape[1] // 2) * 2
    planes, sats, greens = {}, {}, []
    for (dy, dx), (c, letter) in layout.items():
        p = raw[dy:h:2, dx:w:2].astype(np.float32) - float(black[c])
        wl = white_level
        if white_per_channel is not None and len(white_per_channel) > c and white_per_channel[c]:
            wl = white_per_channel[c]
        nominal = float(wl) - float(black[c])
        if nominal <= 0:
            return None   # 白电平不合理(元数据缺失/损坏)：不测，免得把整张判成高光修剪
        sats[(dy, dx)] = _saturation(p, nominal)
        planes[(dy, dx)] = p
        if letter == "G":
            greens.append((dy, dx))
    keys = list(planes)
    clip = {k: planes[k] >= CLIP_FRACTION * sats[k] for k in keys}
    all_clip = clip[keys[0]] & clip[keys[1]] & clip[keys[2]] & clip[keys[3]]
    any_clip = clip[keys[0]] | clip[keys[1]] | clip[keys[2]] | clip[keys[3]]
    ev = SHADOW_EV_HIGH_ISO if (iso or 0) >= HIGH_ISO else SHADOW_EV
    shadow = np.ones_like(all_clip)
    for k in keys:
        shadow &= planes[k] < sats[k] / (2.0 ** ev)
    block = max(scoring.CLIP_BLOCK, round(max(all_clip.shape) / scoring.PREP_LONG_EDGE * scoring.CLIP_BLOCK))
    hl_mask = scoring._keep_patches(all_clip, block)
    color_mask = scoring._keep_patches(any_clip, block) & ~hl_mask
    sh_mask = scoring._keep_patches(shadow, block)
    n = all_clip.size
    g1, g2 = planes[greens[0]], planes[greens[1]]
    sat_g = min(sats[greens[0]], sats[greens[1]])
    curve = _noise_curve(g1, g2, any_clip)
    gmean = (g1 + g2) / 2
    scene_mu = max(float(np.median(gmean[::4, ::4])), 0.005 * sat_g)   # 隔 4 取 1 算中位数：结果一样，快十几倍
    out = {
        "hl_clip_pct": round(100.0 * np.count_nonzero(hl_mask) / n, 2),
        "color_clip_pct": round(100.0 * np.count_nonzero(color_mask) / n, 2),
        "shadow_pct": round(100.0 * np.count_nonzero(sh_mask) / n, 2),
        "snr18_db": None, "snr_scene_db": None, "noise_curve": curve,
        "trust_r": None, "rot": 0, "trusted": jpeg_lum is None,
    }
    if curve is not None:
        s18 = _snr_db(0.18 * sat_g, curve)
        ss = _snr_db(scene_mu, curve)
        out["snr18_db"] = None if s18 is None else round(s18, 1)
        out["snr_scene_db"] = None if ss is None else round(ss, 1)
    if jpeg_lum is not None:
        # RAW 线性值与 JPEG 比秩相关：只看明暗顺序，不受色调曲线影响
        r, k = consistency(gmean, np.asarray(jpeg_lum, dtype=np.float64))
        out["trust_r"] = round(r, 3)
        out["rot"] = k
        out["trusted"] = r >= TRUST_MIN_R
    if want_masks:
        out["masks"] = {"hl": hl_mask, "color": color_mask, "shadow": sh_mask}
    return out


def measure_raw(path, jpeg_rgb=None, iso=None, want_masks=False):
    """读 RAW 文件做测量；读不了/不是拜耳/解坏了(与 JPEG 对不上)都返回 None 或 trusted=False。
    jpeg_rgb：内嵌 JPEG 的 RGB(numpy，任意尺寸)，用于可信度校验。"""
    try:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            jpeg_lum = None
            if jpeg_rgb is not None:
                j = np.asarray(jpeg_rgb, dtype=np.float64)
                jpeg_lum = 0.299 * j[..., 0] + 0.587 * j[..., 1] + 0.114 * j[..., 2]
            wpc = getattr(raw, "camera_white_level_per_channel", None)
            return analyze_mosaic(
                raw.raw_image_visible, raw.raw_colors_visible, raw.black_level_per_channel,
                raw.white_level, white_per_channel=wpc, color_desc=raw.color_desc,
                iso=iso, jpeg_lum=jpeg_lum, want_masks=want_masks,
            )
    except Exception:
        return None
