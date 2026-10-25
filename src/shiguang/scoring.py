"""Phase 2C 自动评分：纯 numpy 实现的客观技术缺陷初筛。

设计依据：docs/superpowers/plans/2026-07-18-shiguang-phase2c-scoring-model.md
（多路调研综合）。核心立场——算法只判"有没有硬伤"（糊/过曝/噪点），
不判"美不美"；三档 = 废(bad)/可修(fix)/精选候选(good)。

流水线：预处理(统一512+预模糊) → S1清晰度(分块VoL+Tenengrad取P90)
→ S2曝光(高光/阴影修剪：有 RAW 用传感器数据，否则用预览上成片无细节的部分) → S3噪点(RAW 实测信噪比 dB)
→ S4定档(硬废闸门一票否决 + 加权评分)。

⚠ 阈值现为"文献默认值"，是**待用户真实照片校准**的量（见设计文档 §3、§6）。
所有阈值都抽成模块常量，校准时改这里即可。数值全部绑定"512长边 + 预模糊"
的预处理，换预处理必须重标。
"""
import io

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image

# 评分算法版本：算法改了就加一。库里记着每张照片是用哪一版评的，旧版评的会算进"待分析"，
# 点一次「开始分析」就用新算法重评(用户手动改过的档不动)。
# v2(2026-10)：死白/死黑只算"成片且没有细节"的区域——以前凡是白到 250 以上都算过曝，白衣服、
# 白鸟、雪、白墙这类本身就白、但纹理层次都还在的东西被大片误判(用户反馈)。
SCORE_VERSION = 4
# v4(2026-10)：分析改为并行、读 RAW 的门槛调整(预览到顶像素 >2% 才去 RAW 核实)；判定规则同 v3。
#    版本号加一让已分析过的照片都重新评一遍(用户要求清掉旧分析结果重跑、顺便看提速效果)。
# v3(2026-10)：高光/阴影修剪与噪点改在 RAW 原始数据上量(raw_analysis，内嵌 JPEG 会把还能救的高光提前
# 显示成"白到顶"、机内降噪又把噪点抹掉)；噪点改用信噪比(dB)判，阈值有出处(见 S3)，不再在 512 小图上
# 量 σ(缩小 10 倍后噪声被平均掉，量到的多半是纹理)。

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

# S2 曝光。"死白"= 三个通道都顶到 T_HIGH 以上、并且周围 5x5 亮度几乎没有起伏(层次被削平、
# 细节真丢了)、并且连成片(8x8 小块里过半都是)——三条同时满足才算。白色物体只要还有纹理就不算；
# 反光点、路灯、太阳这种小亮点也不算(本来就该是白的)。死黑同理。
T_LOW = 5                      # 三通道都 <=此 = 黑到底
T_HIGH = 250                   # 三通道都 >=此 = 白到顶
FLAT_RANGE = 3                # 5x5 邻域亮度极差 <=此 = 没有细节
CLIP_BLOCK = 8                # 成片判定的小块边长(512 长边尺度下；图更大时按比例放大)
CLIP_BLOCK_FILL = 0.5         # 小块里至少这么多比例是"死白/死黑"才算成片
SAT_CHANNEL = 250             # 单通道 >=此 = 该通道裁切
O_HARD_PCT = 8.0             # 高光修剪(成片、细节已丢)占比 >此% → 硬废(RAW 实测，或本身就是 JPG)
O_HARD_PCT_PREVIEW = 25.0    # RAW 文件但只能看内嵌预览时：预览比 RAW 早 1~2 档到顶，硬闸放宽，宁放过不误杀
W_HIGH = 2.5                  # 高光:暗部 判罚权重≈2.5:1（高光不可逆）
W_LOW = 1.0
W_CHANNEL = 0.4              # 单通道爆(红花/霓虹丢色彩细节)的轻权——只轻微降分，
                              # 绝不进 punishment，否则鲜艳精选片会被一票废(调研教训)

# S3 噪点：RAW 实测的"画面中间调信噪比"(dB，见 raw_analysis)。阈值的来历——
#  · ISO 12232 以信噪比 10:1(=20 dB)为"可接受"、40:1(32 dB)为"优秀"；DxOMark 以 18% 灰处 30 dB 为低光线；
#  · 散粒噪声为主时，光线每差 1 档信噪比差约 3 dB；AI 降噪(DxO DeepPRIME、Lightroom 降噪)宣称约能挽回
#    2~3 档 ≈ +6~9 dB(个人实测 2~4 档，过强会涂抹)；
#  · 所以：≥20 dB 不扣分；低于 11 dB 时就算按最乐观的 +9 dB 降噪也到不了 20 dB 的"可接受"线 →
#    判为"救不回来"；中间按信噪比平滑扣分。注：11 dB 是由上述锚点推出的起步线，待真实照片校准。
SNR_OK_DB = 20.0
SNR_HARD_DB = 11.0
# (旧的 512 小图 Immerkær σ 只作参考指标记录在 metrics.sigma 里，不再参与定档)

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
def _local_range(lum, k=5):
    """每个像素 k×k 邻域内的亮度极差(最大-最小)，可分离的滑窗 max/min，纯 numpy。"""
    pad = k // 2
    a = np.pad(lum, pad, mode="edge")
    mx = sliding_window_view(sliding_window_view(a, k, axis=0).max(axis=-1), k, axis=1).max(axis=-1)
    mn = sliding_window_view(sliding_window_view(a, k, axis=0).min(axis=-1), k, axis=1).min(axis=-1)
    return mx.astype(np.int16) - mn.astype(np.int16)


def _keep_patches(mask, block, fill=CLIP_BLOCK_FILL):
    """只保留"成片"的部分：按 block×block 分块，块内过 fill 比例为真才保留这块里的像素。"""
    h, w = mask.shape
    if h < block or w < block:
        return mask
    hh, ww = -(-h // block) * block, -(-w // block) * block
    pm = np.zeros((hh, ww), bool)
    pm[:h, :w] = mask
    area = np.zeros((hh, ww), np.float32)
    area[:h, :w] = 1
    cnt = pm.reshape(hh // block, block, ww // block, block).sum(axis=(1, 3))
    tot = area.reshape(hh // block, block, ww // block, block).sum(axis=(1, 3))
    keep = cnt >= fill * np.maximum(tot, 1)
    return mask & np.repeat(np.repeat(keep, block, axis=0), block, axis=1)[:h, :w]


def clip_masks(rgb):
    """(死白 mask, 死黑 mask)：成片、且没有细节的高光/暗部。rgb 为 uint8 (H,W,3)。"""
    rgb = np.asarray(rgb, dtype=np.uint8)
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.uint8)
    flat = _local_range(lum) <= FLAT_RANGE
    block = max(CLIP_BLOCK, round(max(rgb.shape[:2]) / PREP_LONG_EDGE * CLIP_BLOCK))
    blown = _keep_patches((rgb.min(axis=-1) >= T_HIGH) & flat, block)
    crushed = _keep_patches((rgb.max(axis=-1) <= T_LOW) & flat, block)
    return blown, crushed


def exposure(rgb):
    """死白/死黑(成片无细节，见 clip_masks) + RGB 分通道裁切。返回占比(%)与饱和 mask。

    分通道能抓高饱和色单通道爆（红花/霓虹灰度不亮但已丢细节），灰度会漏。"""
    n = rgb.shape[0] * rgb.shape[1]
    blown, crushed = clip_masks(rgb)
    over = float(np.count_nonzero(blown)) / n * 100
    under = float(np.count_nonzero(crushed)) / n * 100
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


def classify(sharp, expo, sigma, iso=None, raw=None, preview_only_raw=False):
    """把三维度指标合成三档。返回 (tier, reason)。

    raw：raw_analysis 的测量结果(且已通过可信度校验)——有就用 RAW 实测的高光/阴影修剪与信噪比；
    没有就用内嵌预览估算的修剪，噪点未知(不扣分)。preview_only_raw：这是 RAW 文件、但只能看预览。
    第一层硬废闸门(一票否决) → 第二层加权评分定 fix/good 边界。"""
    vol = sharp["vol"]
    if raw:
        over_lum = raw["hl_clip_pct"]                                # 全通道饱和——细节真丢了
        over_any = raw["hl_clip_pct"] + raw["color_clip_pct"]        # 含部分通道饱和——用于降分
        under = raw["shadow_pct"]
        snr = raw.get("snr_scene_db")
        hl_limit = O_HARD_PCT
    else:
        over_lum = expo["over_pct"]                                  # 预览上成片无细节的高光修剪
        over_any = max(expo["over_pct"], expo["over_channel_pct"])   # 含单通道到顶——用于降分
        under = expo["under_pct"]
        snr = None
        hl_limit = O_HARD_PCT_PREVIEW if preview_only_raw else O_HARD_PCT

    # ── 第一层：硬废闸门（顺序：高光修剪 → 严重糊 → 噪点过重）──
    # 高光修剪排在最前：纯白帧应报"高光修剪"而非"模糊"。只看细节真丢了的部分(over_lum)——
    # 单通道饱和是丢色彩细节(红花/霓虹)、可修不直接废，故走加权不进硬闸。
    if over_lum > hl_limit:
        return "bad", ("大面积高光修剪(RAW 实测传感器饱和)，细节无法恢复" if raw
                       else "大面积高光修剪，细节无法恢复")
    # 严重糊：只用 VoL 的 P90(已滤掉低纹理块，天然防极简构图误判)。
    # Tenengrad 绝对值极度依赖内容/对比，不适合当默认硬阈，留作校准期第二意见。
    if vol < VOL_REJECT:
        return "bad", "严重模糊"
    if snr is not None and snr < SNR_HARD_DB:
        return "bad", f"噪点过重(中间调信噪比 {snr:.0f} dB)，降噪也难以救回"

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
    # 噪点子分：RAW 实测信噪比 11→20 dB 平滑升到满分；量不到(非 RAW/RAW 解不了)就不扣分
    s_noise = 1.0 if snr is None else (1.0 if snr >= SNR_OK_DB + 6 else _sigmoid_between(snr, SNR_HARD_DB, SNR_OK_DB))

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


def preview_flags(rgb):
    """预览图上的粗筛信号：决定要不要花时间去读 RAW(读整张 RAW 要几百毫秒)。
    返回 (任一通道到顶的占比%, 亮度中位数)。"""
    n = rgb.shape[0] * rgb.shape[1]
    hot = float(np.count_nonzero(np.any(rgb >= SAT_CHANNEL, axis=-1))) / n * 100
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    return hot, float(np.median(lum))


def needs_raw_check(rgb, iso):
    """这张值得去 RAW 里核实吗：可能有高光修剪(预览上有到顶的像素)、偏暗(阴影修剪/提亮后噪点)、
    或高感光度(噪点)。明亮、低 ISO、没有到顶像素的照片，RAW 里也不会有这些问题，省下读卡时间。"""
    hot, med = preview_flags(rgb)
    # 到顶像素只有零点几(天空一角/反光)时，RAW 里的修剪更少，对定档没有影响——不值得读 25MB 的 RAW。
    # 2%：远低于高光硬阈 8%，又能抓住所有可能被扣分的情况。
    return hot > 2.0 or med < 55 or (iso or 0) >= 3200


def score_image_bytes(image_bytes, iso=None, raw=None, preview_only_raw=False):
    """对外主入口：图片字节 → {tier, reason, metrics}。tier ∈ bad/fix/good。

    raw/preview_only_raw 见 classify。tier 值域与前端/DB 一致：bad=废、fix=可修、good=精选候选。"""
    gray, rgb, gray_raw = _prep(image_bytes)
    sharp = sharpness(gray)
    expo = exposure(rgb)
    sigma = noise_sigma(gray_raw, expo["sat_mask"])
    raw_ok = raw if (raw and raw.get("trusted")) else None
    tier, reason = classify(sharp, expo, sigma, iso=iso, raw=raw_ok,
                            preview_only_raw=preview_only_raw and raw_ok is None)
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
            "measured_on": "raw" if raw_ok else "preview",
            "raw_hl_clip_pct": raw_ok["hl_clip_pct"] if raw_ok else None,
            "raw_color_clip_pct": raw_ok["color_clip_pct"] if raw_ok else None,
            "raw_shadow_pct": raw_ok["shadow_pct"] if raw_ok else None,
            "snr_scene_db": raw_ok["snr_scene_db"] if raw_ok else None,
            "snr18_db": raw_ok["snr18_db"] if raw_ok else None,
        },
    }
