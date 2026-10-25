from PIL import Image

from shiguang import device_watch


# ── list_removable_drives（注入假的位掩码/盘类型，不必真插卡）──────────

def test_list_removable_drives_returns_only_removable():
    # 位掩码：C(bit2) 和 G(bit6) 存在 -> 1<<2 | 1<<6
    bitmask = (1 << 2) | (1 << 6)
    types = {"C:\\": 3, "G:\\": 2}  # C=DRIVE_FIXED(3), G=DRIVE_REMOVABLE(2)

    drives = device_watch.list_removable_drives(
        bitmask_fn=lambda: bitmask,
        type_fn=lambda root: types.get(root, 0),
    )

    assert drives == ["G:\\"]


def test_list_removable_drives_empty_when_none_removable():
    drives = device_watch.list_removable_drives(
        bitmask_fn=lambda: (1 << 2),        # 只有 C
        type_fn=lambda root: 3,             # 都是 fixed
    )
    assert drives == []


def test_list_removable_drives_survives_bitmask_error():
    def boom():
        raise OSError("kernel32 炸了")
    assert device_watch.list_removable_drives(bitmask_fn=boom) == []


# ── find_photo_folders ────────────────────────────────────────────

def test_find_photo_folders_finds_dirs_with_photos(tmp_path):
    dcim = tmp_path / "DCIM" / "100NZ502"
    dcim.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(dcim / "a.jpg")
    Image.new("RGB", (10, 10)).save(dcim / "b.jpg")
    (dcim / "notes.txt").write_text("ignore")   # 非照片不计数
    empty = tmp_path / "DCIM" / "EMPTY"
    empty.mkdir()                                 # 无照片的目录不出现

    folders = device_watch.find_photo_folders(str(tmp_path))

    assert len(folders) == 1
    assert folders[0]["name"] == "100NZ502"
    assert folders[0]["count"] == 2
    assert folders[0]["size_mb"] >= 0


def test_find_photo_folders_respects_max_depth(tmp_path):
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(deep / "x.jpg")

    # max_depth=2 时 e 目录(深度5)不该被扫到
    folders = device_watch.find_photo_folders(str(tmp_path), max_depth=2)

    assert folders == []


# ── DeviceWatcher.poll_once（diff 逻辑，不起线程）──────────────────

def test_poll_once_does_not_report_drives_present_at_construction():
    """基线在构造时捕获：开机已插着的卡不由 watcher 上报(交给 detect_cards_now)，
    避免和启动主动检测重复弹窗。"""
    w = device_watch.DeviceWatcher(on_card_inserted=lambda d: None, list_fn=lambda: ["G:\\"])
    assert w.poll_once() == set()          # G 在构造时就在，不算"新插入"


def test_poll_once_only_reports_newly_added_after_construction():
    drives = {"cur": ["G:\\"]}
    w = device_watch.DeviceWatcher(on_card_inserted=lambda d: None, list_fn=lambda: list(drives["cur"]))

    assert w.poll_once() == set()          # 构造时 G 已在 → 不报
    drives["cur"] = ["G:\\", "H:\\"]      # 之后插了 H
    assert w.poll_once() == {"H:\\"}      # 只报新增的 H
    drives["cur"] = ["H:\\"]              # 拔掉 G
    assert w.poll_once() == set()          # 拔卡不触发插入回调


def test_poll_once_reports_readded_drive():
    drives = {"cur": ["G:\\"]}
    w = device_watch.DeviceWatcher(on_card_inserted=lambda d: None, list_fn=lambda: list(drives["cur"]))
    drives["cur"] = []                     # 先拔掉构造时就在的 G
    w.poll_once()
    drives["cur"] = ["G:\\"]              # 重新插回
    assert w.poll_once() == {"G:\\"}      # 重新插入应再次上报


# ── read_volume_serial（认卡用卷序列号）──────────────────

def test_read_volume_serial_formats_hex():
    """把 GetVolumeInformation 返回的32位整数格式成8位大写十六进制。"""
    s = device_watch.read_volume_serial("F:\\", serial_fn=lambda root: 0x1A2B3C4D)
    assert s == "1A2B3C4D"


def test_read_volume_serial_zero_treated_as_none():
    """序列号为0(未正常格式化/虚拟卷)当作读不到，避免多卡共享同一编号串档(M2)。"""
    assert device_watch.read_volume_serial("F:\\", serial_fn=lambda root: 0) is None


def test_read_volume_serial_failure_returns_none():
    assert device_watch.read_volume_serial("F:\\", serial_fn=lambda root: None) is None

    def boom(root):
        raise OSError("no volume")
    assert device_watch.read_volume_serial("F:\\", serial_fn=boom) is None
