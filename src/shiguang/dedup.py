"""相似去重 + 连拍折叠的纯逻辑（无 UI、无 DB）：感知哈希 + 分组。

设计（用户定案 2026-07-19）：
- 感知哈希用 dHash（相邻像素梯度，纯 numpy，比 pHash 简单、对缩放/轻微改动稳）。
- 一个"堆叠(stack)"= 一组近乎重复/连拍的照片，两个**独立**布尔标识：
    · burst(连拍)：同机型 + 拍摄时间相邻(<=BURST_GAP_SEC) —— 不管画面像不像；
    · similar(相似)：dHash 汉明距离 <=SIMILAR_MAX_HAMMING —— **只在同一天内**两两比
      (用户观察:重复几乎都在同一天同地点;同天内比也避免拿全库 O(n^2) 拖慢/误并几月前的像片)。
  一个 stack 可同时是连拍且相似 / 只连拍 / 只相似。
- 组内按 focus_score(主体锐度)降序，最锐那张当封面 cover + 推荐保留。
"""
import io
from collections import defaultdict
from datetime import datetime

import numpy as np
from PIL import Image

BURST_GAP_SEC = 2.0          # 拍摄时间相邻这么多秒内 + 同机型 = 连拍(EXIF 秒级精度，连拍常同秒)
SIMILAR_MAX_HAMMING = 8      # dHash(64bit) 汉明距离 <=此 = 画面相似(0=几乎同帧)
LOW_TEX_MIN_BITS = 5         # dHash 置位数 <此 或 >64-此 = 近均匀图(全黑/全白/纯色)，哈希会雷同
                             # → 不参与相似合并，免把不相干的近空白图误并成一堆(审查 Important1)
_DHASH_SIZE = 8              # 8x9 灰度 → 8x8 梯度 = 64 位


def dhash(image_bytes, hash_size=_DHASH_SIZE):
    """dHash：缩到 (size+1) x size 灰度，比较每行相邻像素大小 → size*size 位，返回16位十六进制串。
    内容相近的图哈希也相近(汉明距离小)；纯算法零模型。"""
    img = Image.open(io.BytesIO(image_bytes)).convert("L").resize(
        (hash_size + 1, hash_size), Image.BILINEAR
    )
    a = np.asarray(img, dtype=np.int16)
    diff = a[:, 1:] > a[:, :-1]          # (size, size) 布尔
    val = 0
    for bit in diff.flatten():
        val = (val << 1) | int(bit)
    return format(val, "0{}x".format(hash_size * hash_size // 4))


def hamming(hex_a, hex_b):
    """两个十六进制 dHash 的汉明距离(不同位数)。任一为空 → 返回一个大数(视为不相似)。"""
    if not hex_a or not hex_b:
        return 999
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def _low_texture(hex_h):
    """dHash 置位数接近 0 或 64 = 近均匀图(全黑/全白/纯色)——这类图哈希彼此雷同，
    会把内容不相干的近空白照片误判成"相似"。这些不参与相似合并。"""
    if not hex_h:
        return True
    ones = bin(int(hex_h, 16)).count("1")
    return ones < LOW_TEX_MIN_BITS or ones > (64 - LOW_TEX_MIN_BITS)


def _parse_time(s):
    """'YYYY-MM-DD HH:MM:SS' → datetime；非法/空 → None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


class _UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def group_stacks(items, burst_gap_sec=BURST_GAP_SEC, similar_max_hamming=SIMILAR_MAX_HAMMING):
    """把照片分成堆叠。items = [{id, capture_time(str|None), cam, phash(hex|None), focus_score(float|None)}]。
    返回 [{id:'stack-N', memberIds:[最锐在前], cover:最锐id, burst:bool, similar:bool}]，只含 >=2 张的组。
    连拍按时间相邻并查集合并；相似按同一天内两两汉明距离合并；连拍/相似标识分别按各自产生的边判定。"""
    n = len(items)
    if n < 2:
        return []
    uf = _UnionFind(n)

    # ── 只按"相似"分组(用户定案B)：纯连拍(时间相邻但姿势可能不同→画面不相似)**不折叠**，
    #    平铺展示；只有画面 dHash 接近才折叠成堆。相似只在"同一天且有拍摄时间"内两两比
    #    (重复几乎都在同一天同地点;也避免全库O(n^2)+误并)。近均匀图(全黑/全白/纯色)哈希雷同,跳过。──
    by_day = defaultdict(list)
    for k in range(n):
        ct = items[k].get("capture_time")
        if ct and items[k].get("phash"):
            by_day[ct[:10]].append(k)
    for members in by_day.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if _low_texture(items[a]["phash"]) or _low_texture(items[b]["phash"]):
                    continue
                if hamming(items[a]["phash"], items[b]["phash"]) <= similar_max_hamming:
                    uf.union(a, b)

    # ── 收敛成分量，排序取封面(每个堆都是"相似"组，不再有连拍标识)──
    comps = defaultdict(list)
    for k in range(n):
        comps[uf.find(k)].append(k)

    stacks = []
    # 按分量最早拍摄时间排序，让 stack 编号稳定、连拍组按时间先后出现
    def comp_key(root):
        times = [_parse_time(items[k].get("capture_time")) for k in comps[root]]
        times = [t for t in times if t]
        return (not times, min(times) if times else datetime.max)

    for root in sorted(comps, key=comp_key):
        members = comps[root]
        if len(members) < 2:
            continue
        # 组内按主体锐度降序(None 最后)，最锐当封面/推荐保留
        members_sorted = sorted(
            members,
            key=lambda k: (items[k].get("focus_score") is None,
                           -(items[k].get("focus_score") or 0.0)),
        )
        member_ids = [items[k]["id"] for k in members_sorted]
        stacks.append({
            "id": "stack-{}".format(len(stacks) + 1),
            "memberIds": member_ids,
            "cover": member_ids[0],
            "burst": False,          # 用户定案B:不再按连拍折叠,故堆叠一律非连拍
            "similar": True,         # 能成堆的都是画面相似组
        })
    return stacks
