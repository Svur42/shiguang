"""相似去重/连拍分组的行为契约测试。dhash 用合成图，group_stacks 直接喂受控 phash/时间。"""
import io

import numpy as np
from PIL import Image

from shiguang import dedup


def _jpeg(arr):
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _gradient(size=256, shift=0):
    y = np.linspace(20 + shift, 220 + shift, size)[:, None] * np.ones((1, size))
    x = np.linspace(0, 40, size)[None, :] * np.ones((size, 1))
    g = np.clip(y + x, 0, 255)
    return np.stack([g] * 3, axis=-1).astype(np.uint8)


# ── dhash ────────────────────────────────────────────────
def test_dhash_deterministic_and_16_hex():
    h = dedup.dhash(_jpeg(_gradient()))
    assert h == dedup.dhash(_jpeg(_gradient()))
    assert len(h) == 16 and all(c in "0123456789abcdef" for c in h)


def test_dhash_similar_closer_than_different():
    base = dedup.dhash(_jpeg(_gradient()))
    near = dedup.dhash(_jpeg(_gradient(shift=6)))          # 轻微变亮 = 相似
    far = dedup.dhash(_jpeg(np.fliplr(_gradient())))        # 左右翻转 = 很不一样
    assert dedup.hamming(base, near) < dedup.hamming(base, far)


def test_hamming_empty_is_large():
    assert dedup.hamming(None, "0000000000000000") >= 64
    assert dedup.hamming("", "ffffffffffffffff") >= 64


# ── group_stacks ─────────────────────────────────────────
def _item(id, t, cam="R5", phash="0000000000000000", score=100.0):
    return {"id": id, "capture_time": t, "cam": cam, "phash": phash, "focus_score": score}


def test_pure_burst_not_grouped():
    """用户定案B:纯连拍(时间相邻但画面不相似)不折叠——不成组。"""
    items = [
        _item(1, "2024-06-01 10:00:00", phash="00ff00ff00ff00ff", score=100),
        _item(2, "2024-06-01 10:00:01", phash="ff00ff00ff00ff00", score=200),  # 相邻1s但hamming大=不相似
        _item(3, "2024-06-01 10:00:02", phash="0f0f0f0f0f0f0f0f", score=50),
    ]
    assert dedup.group_stacks(items) == []


def test_similar_groups_and_is_marked_similar():
    """画面相似→折叠成组，标 similar、非 burst；最锐当封面。"""
    items = [
        _item(10, "2024-06-01 10:00:00", phash="00ff00ff00ff00ff", score=100),
        _item(11, "2024-06-01 10:05:00", phash="00ff00ff00ff00fe", score=80),  # 隔5分钟但画面相似 hamming=1
    ]
    stacks = dedup.group_stacks(items)
    assert len(stacks) == 1
    assert stacks[0]["burst"] is False and stacks[0]["similar"] is True
    assert stacks[0]["cover"] == 10


def test_low_texture_not_merged_as_similar():
    """近均匀图(全黑/全白/纯色, dHash 置位数接近0/64)哈希雷同，不该被当'相似'并组。"""
    items = [
        _item(1, "2024-06-01 10:00:00", phash="0000000000000000", score=100),  # 全黑, 0位
        _item(2, "2024-06-01 10:05:00", phash="0000000000000001", score=80),   # 近全黑, 1位; 时间远非连拍
    ]
    assert dedup.group_stacks(items) == []


def test_untimed_photos_not_similar_grouped():
    """无拍摄时间的照片不做相似合并(没有'同一天同地点'前提，避免全库误并)。"""
    items = [
        _item(1, None, phash="00ff00ff00ff00ff", score=100),
        _item(2, None, phash="00ff00ff00ff00ff", score=80),   # 哈希完全相同但都无时间
    ]
    assert dedup.group_stacks(items) == []


def test_burst_that_is_also_similar_still_groups():
    """连拍且画面也相似的→仍折叠(因为相似)，标 similar；不再有 burst 标识。"""
    items = [
        _item(20, "2024-06-01 10:00:00", phash="00ff00ff00ff00ff", score=100),
        _item(21, "2024-06-01 10:00:01", phash="00ff00ff00ff00fe", score=90),  # 相邻1s + 画面相似 hamming=1
    ]
    s = dedup.group_stacks(items)[0]
    assert s["burst"] is False and s["similar"] is True


def test_similar_only_within_same_day():
    """相似比对只在同一天内：跨天的相似片不合并(用户观察:重复都在一天内)。"""
    items = [
        _item(30, "2024-06-01 10:00:00", phash="0000000000000000"),
        _item(31, "2024-06-02 10:00:00", phash="0000000000000000"),  # 完全相同哈希但隔天
    ]
    assert dedup.group_stacks(items) == []


def test_singletons_excluded():
    items = [
        _item(1, "2024-06-01 10:00:00", phash="0000000000000000"),
        _item(2, "2024-06-05 12:00:00", phash="ffffffffffffffff"),   # 不同天+不相似+非相邻
    ]
    assert dedup.group_stacks(items) == []
