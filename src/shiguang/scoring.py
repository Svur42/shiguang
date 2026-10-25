"""Phase 2C 自动评分：纯 numpy 实现的客观技术缺陷初筛。

设计依据：docs/superpowers/plans/2026-07-18-shiguang-phase2c-scoring-model.md
（多路调研综合）。核心立场——算法只判"有没有硬伤"（糊/过曝/噪点），
不判"美不美"；三档 = 废(bad)/可修(fix)/精选候选(good)。

流水线：预处理(统一512+预模糊) → S1清晰度(分块VoL+Tenengrad取P90)
→ S2曝光(灰度两尾+RGB分通道裁切) → S3噪点(Immerkær，先扣饱和区)
→ S4定档(硬废闸门一票否决 + 加权评分)。

⚠ 阈值现为"文献默认值"，是**待用户真实照片校准**的量（见设计文档 §3、§6）。
所有阈值都抽成模块常量，校准时改这里即可。数值全部绑定"512长边 + 预模糊"
的预处理，换预处理必须重标。
"""
import io

import numpy as np
from PIL import Image

# ── 待校准阈值（文献默认值，绑定 512 长边灰度 + 3x3 高斯预模糊）──────────
PREP_LONG_EDGE = 512          # 统一到这个长边再算，VoL/Tenengrad 对分辨率极敏感
GRID = 8                       # 分块网格 8x8=64 块，取 P90 块 = "主体最清晰处"
TEX_MIN = 6.0                  # 块灰度标准差低于此=低纹理(天空/纯墙)，不参与清晰度

# S1 清晰度（512+预模糊尺度下的经验量级，务必校准）
VOL_REJECT = 40.0              # 分块P90 VoL 低于此 → 严重糊(废)
VOL_KEEP = 180.0              # 高于此算"够清晰"；VOL_REJECT~VOL_KEEP 之间= 边界(可修)
VOL_GOOD = 600.0             # 高于此清晰度满分

# S1b 主体/对焦定位（浅景深鸟/虫：主体锐、背景糊。判"对焦有没有锁在一个主体上"）——
# 方案①零模型：不认物种，只找"最锐的块簇"当被对焦的主体，据此判对焦落点并给锐度托底。
FOCUS_RATIO_MIN = 1.8        # 主体块P90 / 有效块中位数 >=此 → 主体与背景锐度分离明显(像有意浅景深对焦)
FOCUS_LOCALITY_MIN = 0.45    # 高锐块在其包围盒里的填充率 >=此 → 锐块聚成一个主体(非四散/无锁定)
FOCUS_MIN_BLOCKS = 2         # 主体块簇至少这么多块 且 包围盒两维都>=2：排除"单块/一条线"型
                             # 假主体(相机日期戳/水印文字带/锐利地平线)被误当对焦主体托底
SUBJECT_LOCK_FLOOR = 0.7     # 确认"对焦锁定主体"时给清晰度子分的下限：主体针尖锐却因背景虚化
                             # 拉低全局时，不让它被低估(这正是拍鸟/虫最容易被误杀的场景)

# S2 曝光
T_LOW = 5                      # <=此=暗部死黑
T_HIGH = 250                   # >=此=高光死白
SAT_CHANNEL = 250             # 单通道 >=此 = 该通道裁切
O_HARD_PCT = 8.0             # 亮度过曝(死白)占比 >此% → 硬废(死白不可逆)
W_HIGH = 2.5                  # 高光:暗部 判罚权重≈2.5:1（高光不可逆）
W_LOW = 1.0
W_CHANNEL = 0.4              # 单通道爆(红花/霓虹丢色彩细节)的轻权——只轻微降分，
                              # 绝不进 punishment，否则鲜艳精选片会被一票废(调研教训)

# S3 噪点（Immerkær σ，0~255 灰度级）
SIGMA_HARD = 18.0            # σ>此 且清晰度不足 → 极端噪点(废)
SIGMA_OK = 4.0               # σ<此=干净
SIGMA_BAD = 12.0            # σ>此=噪点明显(单独不废，进可修/降分)
ISO_NOISE_RELAX = 3200      # ISO 高于此放宽噪点容忍(高ISO噪点预期内)
ISO_RELAX_FACTOR = 1.6       # 放宽倍数

# S4 加权定档
W_SHARP, W_EXPO, W_NOISE = 0.5, 0.3, 0.2
PUNISH_TH = 0.25             # 任一子分低于此 → 大幅压总分(软性一票否决)
T_KEEP = 0.62               # 综合分>=此 → 精选候选(good)；宜松防误杀
T_EDIT = 0.35               # >=此 → 可修(fix)；否则 废(bad)


# ── 预处理 ────────────────────────────────────────────────
_LAP = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], np.float64)
_SOBEL_X = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], np.float64)
_SOBEL_Y = _SOBEL_X.T
_IMMERKAER = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float64)
_GAUSS = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float64) / 16.0


def _conv3_valid(a, k):
    """纯 numpy 3x3 卷积（valid，返回内部 (H-2, W-2)）。避免引入 scipy/cv2。
    图太小（任一边 <3）无法做 valid 卷积，返回空数组由上层兜底，不抛负维度异常。"""
    h, w = a.shape
    if h < 3 or w < 3:
        return np.zeros((0, 0), np.float64)
    out = np.zeros((h - 2, w - 2), np.float64)
    for di in range(3):
        for dj in range(3):
            out += k[di, dj] * a[di:di + h - 2, dj:dj + w - 2]
    return out


def _prep(image_bytes):
    """解码 → 统一长边512 → 返回 (预模糊灰度 float64, RGB uint8, 原始灰度 float64)。

    RGB 保持原色用于曝光/分通道裁切；预模糊灰度用于清晰度（防噪点被当边缘抬高分）；
    原始灰度用于噪点估计（噪点估计必须在未模糊图上做，否则噪声被预模糊磨掉）。"""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    scale = PREP_LONG_EDGE / max(w, h)
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR)
    rgb = np.asarray(img, dtype=np.uint8)
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    # 3x3 高斯预模糊（边缘用 valid 后 pad 回原尺寸，保持形状一致）
    blurred = lum.copy()
    if lum.shape[0] > 2 and lum.shape[1] > 2:
        blurred[1:-1, 1:-1] = _conv3_valid(lum, _GAUSS)
    return blurred, rgb, lum


# ── S1 清晰度 ─────────────────────────────────────────────
def sharpness(gray):
    """分块 Variance of Laplacian + Tenengrad，取有纹理块的 P90。

    P90 而非全图平均：浅景深/微距的虚化背景会把均值拉低误杀精选片；
    取"最清晰的那块"，整体脱焦废片则所有块都低。低纹理块(天空/纯墙)剔除。"""
    neutral = {"vol": VOL_KEEP, "ten": 0.0, "low_texture": True,
               "subject_vol": VOL_KEEP, "focus_ratio": 1.0,
               "focus_locality": 0.0, "subject_center": None}
    if gray.shape[0] < 3 or gray.shape[1] < 3:   # 太小无法算清晰度 → 中性兜底(不误废)
        return neutral
    lap = _conv3_valid(gray, _LAP)
    gx = _conv3_valid(gray, _SOBEL_X)
    gy = _conv3_valid(gray, _SOBEL_Y)
    ten = gx ** 2 + gy ** 2
    g_in = gray[1:-1, 1:-1]

    h, w = lap.shape
    # 保留 8x8 的二维块结构(而非拍平)：主体/对焦定位要看"锐块在画面里怎么分布"。
    vol_map = np.full((GRID, GRID), np.nan)
    ten_map = np.full((GRID, GRID), np.nan)
    tex_map = np.full((GRID, GRID), np.nan)
    for i in range(GRID):
        for j in range(GRID):
            r0, r1 = i * h // GRID, (i + 1) * h // GRID
            c0, c1 = j * w // GRID, (j + 1) * w // GRID
            if r1 <= r0 or c1 <= c0:
                continue
            vol_map[i, j] = lap[r0:r1, c0:c1].var()
            ten_map[i, j] = ten[r0:r1, c0:c1].mean()
            tex_map[i, j] = g_in[r0:r1, c0:c1].std()
    valid = np.isfinite(vol_map) & (tex_map > TEX_MIN)
    low_texture = bool(valid.sum() < 3)   # 先记录回退是否真发生（覆盖 valid 前）
    if low_texture:      # 几乎全是低纹理（极简构图）→ 退回用全部有效块，别误杀
        valid = np.isfinite(vol_map)
    if not valid.any():
        return neutral
    vols = vol_map[valid]
    vol_p90 = float(np.percentile(vols, 90))
    subj = _subject_focus(vol_map, valid, vol_p90)
    return {
        "vol": vol_p90,
        "ten": float(np.percentile(ten_map[valid], 90)),
        "low_texture": low_texture,
        **subj,
    }


def _subject_focus(vol_map, valid, vol_p90):
    """把锐度块图变成"对焦落点"信息(方案①的核心，零模型)：
      - subject_vol：最锐块簇的平均锐度 = "主体区清晰度"(比单个 P90 块更稳)；
      - focus_ratio：主体块P90 / 有效块中位数 = 主体与背景的锐度分离度。浅景深有意
        对焦时主体远锐于虚化背景→比值高；整幅均匀(风景/均匀糊)→比值≈1；
      - focus_locality：高锐块在其包围盒内的填充率 = 锐块聚不聚成一个主体。一簇=高(对焦
        锁在一个主体上)；四散=低(没锁定/到处一点点纹理)；
      - subject_center：主体块簇质心(y,x 归一 0~1)，供 UI 以后标"对焦点"，此处只记录。"""
    vols = vol_map[valid]
    med = float(np.median(vols))
    focus_ratio = min(vol_p90 / (med + 1e-6), 99.0) if med > 0 else 99.0
    peak = float(vols.max())
    thr = max(VOL_KEEP, 0.5 * peak)          # 高锐块 = 够清晰 且 达峰值一半以上
    top = valid & (vol_map >= thr)
    if not top.any():
        return {"subject_vol": vol_p90, "focus_ratio": focus_ratio,
                "focus_locality": 0.0, "subject_center": None,
                "subject_peak": peak, "focus_blocks": 0, "focus_span": 0}
    rows, cols = np.where(top)
    span_r = int(rows.max() - rows.min() + 1)
    span_c = int(cols.max() - cols.min() + 1)
    locality = float(top.sum()) / float(span_r * span_c)
    subject_vol = float(np.mean(vol_map[top]))
    center = ((float(rows.mean()) + 0.5) / GRID, (float(cols.mean()) + 0.5) / GRID)
    # subject_peak=簇内最锐块(真实幅度，非均值——均值受 thr 下限影响恒偏高)；
    # focus_blocks=主体占几块；focus_span=包围盒较短的一维(=1 即退化成一条线/一个点)。
    return {"subject_vol": subject_vol, "focus_ratio": focus_ratio,
            "focus_locality": locality, "subject_center": center,
            "subject_peak": peak, "focus_blocks": int(top.sum()),
            "focus_span": min(span_r, span_c)}


# ── S2 曝光 ───────────────────────────────────────────────
def exposure(rgb):
    """灰度两尾裁切 + RGB 分通道裁切。返回占比(%)与饱和 mask。

    分通道能抓高饱和色单通道爆（红花/霓虹灰度不亮但已丢细节），灰度会漏。"""
    y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    n = y.size
    over = float(np.count_nonzero(y >= T_HIGH)) / n * 100
    under = float(np.count_nonzero(y <= T_LOW)) / n * 100
    chan_clip = [float(np.count_nonzero(rgb[..., c] >= SAT_CHANNEL)) / n * 100 for c in range(3)]
    sat_mask = np.any(rgb >= SAT_CHANNEL, axis=-1)
    return {
        "over_pct": round(over, 2),
        "under_pct": round(under, 2),
        "over_channel_pct": round(max(chan_clip), 2),
        "sat_mask": sat_mask,
    }


# ── S3 噪点 ───────────────────────────────────────────────
def noise_sigma(gray, sat_mask):
    """Immerkær 3x3 快速噪声估计。先扣掉饱和/裁切区，否则被当噪声高估 σ。"""
    conv = np.abs(_conv3_valid(gray, _IMMERKAER))
    if conv.size == 0:
        return 0.0
    # 饱和 mask 对齐到 valid 内部，再向四邻膨胀一圈：3x3 核在饱和区外一圈的输出
    # 也被裁切像素污染，一并排除，避免在死白/死黑边界高估 σ。
    sm = sat_mask[1:-1, 1:-1]
    d = sm.copy()
    d[:-1] |= sm[1:]
    d[1:] |= sm[:-1]
    d[:, :-1] |= sm[:, 1:]
    d[:, 1:] |= sm[:, :-1]
    vals = conv[~d]
    if vals.size == 0:
        return 0.0
    return float(vals.sum() * np.sqrt(np.pi / 2) / (6 * vals.size))


# ── S4 综合定档 ───────────────────────────────────────────
def _sigmoid_between(x, lo, hi):
    """把 x 从 [lo, hi] 平滑映射到 (0,1)，lo→~0.12, hi→~0.88。"""
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    t = (x - lo) / (hi - lo)
    return float(1.0 / (1.0 + np.exp(-6.0 * (t - 0.5))))


def classify(sharp, expo, sigma, iso=None):
    """把三维度指标合成三档。返回 (tier, reason)。

    第一层硬废闸门(一票否决) → 第二层加权评分定 fix/good 边界。"""
    vol = sharp["vol"]
    over_lum = expo["over_pct"]                              # 亮度过曝(全通道级)——真死白
    over_any = max(expo["over_pct"], expo["over_channel_pct"])  # 含单通道爆——用于降分
    under = expo["under_pct"]

    # ISO 自适应：高 ISO 放宽噪点阈值（高 ISO 噪点是预期内的）
    sigma_bad = SIGMA_BAD
    sigma_hard = SIGMA_HARD
    if iso and iso >= ISO_NOISE_RELAX:
        sigma_bad *= ISO_RELAX_FACTOR
        sigma_hard *= ISO_RELAX_FACTOR

    # ── 第一层：硬废闸门（顺序：曝光死白 → 严重糊 → 极端噪点）──
    # 高光死白排在最前：纯白帧应报"死白"而非"模糊"。只看亮度过曝(over_lum)——
    # 单通道爆是丢色彩细节(红花/霓虹)、可修不直接废，故走加权不进硬闸。
    if over_lum > O_HARD_PCT:
        return "bad", "高光死白不可恢复"
    # 严重糊：只用 VoL 的 P90(已滤掉低纹理块，天然防极简构图误判)。
    # Tenengrad 绝对值极度依赖内容/对比，不适合当默认硬阈，留作校准期第二意见。
    if vol < VOL_REJECT:
        return "bad", "严重模糊"
    if sigma > sigma_hard and vol < VOL_KEEP:
        return "bad", "极端噪点"

    # ── 第二层：加权评分 ──
    # 清晰度只参与加权、不进 punishment：调研头号教训是"重锐度误杀稍软的决定性瞬间"，
    # 所以稍软的片让它自然落到"可修"给人看，而不是被清晰度一票压成废。
    s_sharp = _sigmoid_between(vol, VOL_KEEP, VOL_GOOD)
    # 对焦锁定托底(方案①)：主体区够锐 + 主体明显锐于背景(浅景深) + 锐块聚成一簇 →
    # 判定"对焦确实锁在一个主体上"，给清晰度子分一个下限。这样"鸟眼针尖锐、背景全虚化"
    # 的精选片不会因为背景把全局锐度指标拉软而被低估——拍鸟/微距最容易被误杀的场景。
    # ratio 门槛挡掉"整幅均匀轻糊"(ratio≈1不触发)，故不会把普通软片错托成精选。
    has_subject_lock = (
        not sharp.get("low_texture", False)                         # 极简/低纹理回退时中位数被拉低→ratio虚高，禁用托底
        and sharp.get("subject_peak", 0.0) >= VOL_GOOD              # 主体真的很锐(真实幅度闸，非恒真)
        and sharp.get("focus_blocks", 0) >= FOCUS_MIN_BLOCKS        # 主体够大，排除单块水印/日期戳
        and sharp.get("focus_span", 0) >= 2                         # 2D 团块非一条线/一个点，排除地平线/水印带
        and sharp.get("focus_ratio", 1.0) >= FOCUS_RATIO_MIN        # 主体明显锐于背景(浅景深)
        and sharp.get("focus_locality", 0.0) >= FOCUS_LOCALITY_MIN  # 锐块聚成一簇
    )
    if has_subject_lock:
        s_sharp = max(s_sharp, SUBJECT_LOCK_FLOOR)
    # 曝光子分拆两块，防单通道爆误杀鲜艳精选片：
    #  hard = 亮度过曝(死白) + 暗部死黑 —— 真丢数据，高光判罚重于暗部(不对称)，进 punishment
    #  soft = 单通道爆超出亮度过曝的部分(红花/霓虹丢色彩细节) —— 轻权降分、绝不进 punishment
    s_expo_hard = max(0.0, 1.0 - min(1.0, (W_HIGH * over_lum + W_LOW * under) / 100.0))
    channel_only = max(0.0, over_any - over_lum)
    s_expo = max(0.0, s_expo_hard - W_CHANNEL * channel_only / 100.0)
    s_noise = 1.0 - _sigmoid_between(sigma, SIGMA_OK, sigma_bad)

    score = W_SHARP * s_sharp + W_EXPO * s_expo + W_NOISE * s_noise
    # punishment 只作用于"真丢数据"的硬缺陷(亮度死白/死黑、噪点)：这两类极低才软性一票
    # 否决。单通道爆(s_expo 的 soft 部分)刻意排除，否则鲜艳色彩会被从后门一票压成废。
    for s in (s_expo_hard, s_noise):
        if s < PUNISH_TH:
            score *= s / PUNISH_TH

    if score >= T_KEEP:
        return "good", "无明显硬伤"
    if score >= T_EDIT:
        return "fix", "有可修复缺陷"
    return "bad", "综合质量过低"


def score_image_bytes(image_bytes, iso=None):
    """对外主入口：图片字节 → {tier, reason, metrics}。tier ∈ bad/fix/good。

    tier 值域与前端/DB 一致：bad=废、fix=可修、good=精选候选。"""
    gray, rgb, gray_raw = _prep(image_bytes)
    sharp = sharpness(gray)
    expo = exposure(rgb)
    sigma = noise_sigma(gray_raw, expo["sat_mask"])
    tier, reason = classify(sharp, expo, sigma, iso=iso)
    return {
        "tier": tier,
        "reason": reason,
        "metrics": {
            "vol": round(sharp["vol"], 1),
            "ten": round(sharp["ten"], 1),
            "low_texture": sharp["low_texture"],
            "subject_vol": round(sharp.get("subject_vol", sharp["vol"]), 1),
            "subject_peak": round(sharp.get("subject_peak", sharp["vol"]), 1),
            "focus_ratio": round(sharp.get("focus_ratio", 1.0), 2),
            "focus_locality": round(sharp.get("focus_locality", 0.0), 2),
            "focus_blocks": sharp.get("focus_blocks", 0),
            "focus_span": sharp.get("focus_span", 0),
            "subject_center": sharp.get("subject_center"),
            "over_pct": expo["over_pct"],
            "under_pct": expo["under_pct"],
            "over_channel_pct": expo["over_channel_pct"],
            "sigma": round(sigma, 2),
        },
    }
