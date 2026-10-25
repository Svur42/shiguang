"""可移动存储设备（SD/CF/CFexpress 等，经读卡器接入）自动检测。

设计依据：设计单 §3.3 Phase 2E。纯 ctypes 调 Windows kernel32，不引入第三方库
（不依赖 pywin32/wmi）。用轮询而非 WM_DEVICECHANGE 事件：
  - 轮询成本极低——GetLogicalDrives 返回一个 32 位整数(每个盘符一位)，
    每 2 秒调一次几乎零开销；
  - WM_DEVICECHANGE 需要 hook 窗口消息、拿 pywebview 窗口句柄做子类化，脆弱且
    跟 2F 窗口动画一样娇气；对"插卡弹窗"这种秒级响应够用的场景，轮询更务实可靠。

已知限制(automation-design.1：风险配对策)：少数专业 CFexpress 读卡器会把卡报成
DRIVE_FIXED 而非 DRIVE_REMOVABLE，那样不会被自动检测到——用户仍可用侧边栏
「导入新存储卡…」按钮手动选文件夹导入作为兜底。
"""
import threading

from . import scanner

_DRIVE_REMOVABLE = 2  # Windows GetDriveType 返回值：可移动盘


def _logical_drives_bitmask():
    import ctypes
    return ctypes.windll.kernel32.GetLogicalDrives()


def _drive_type(root):
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))


def list_removable_drives(bitmask_fn=_logical_drives_bitmask, type_fn=_drive_type):
    """返回当前所有可移动盘的根路径列表，如 ['G:\\\\', 'H:\\\\']。
    两个函数参数是为了单元测试能注入假的位掩码/盘类型，不必真插卡。"""
    try:
        bitmask = bitmask_fn()
    except Exception:
        return []
    drives = []
    for i in range(26):
        if bitmask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            try:
                if type_fn(root) == _DRIVE_REMOVABLE:
                    drives.append(root)
            except Exception:
                pass
    return drives


def _read_volume_serial_win(root):
    """真实读盘：ctypes 调 GetVolumeInformationW 取卷序列号(32位无符号整数)。"""
    import ctypes

    serial = ctypes.c_uint32(0)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root),  # lpRootPathName，如 'F:\\'
        None, 0,                 # 卷标缓冲(不要)
        ctypes.byref(serial),    # lpVolumeSerialNumber
        None, None, None, 0,     # 其余不要
    )
    if not ok:
        return None
    return serial.value


def read_volume_serial(root, serial_fn=_read_volume_serial_win):
    """返回该盘卷序列号的 8 位十六进制字符串(如 '1A2B3C4D')；读不到/为0 返回 None。

    序列号为 0 一并当作"读不到"：某些未正常格式化/虚拟卷会返回 0，若当有效编号存库，
    多张这样的卡会共享同一编号导致认卡串档。serial_fn 便于单测注入假实现。"""
    try:
        val = serial_fn(root)
    except Exception:
        return None
    if not val:  # None 或 0
        return None
    return f"{int(val) & 0xFFFFFFFF:08X}"


def find_photo_folders(root, max_depth=4, max_folders=300, max_dirs=4000):
    """在盘里找"直接包含照片的文件夹"，返回 [{path, name, count, size_mb}]。

    有界遍历，防大盘/多杂文件时卡住：
      - max_depth：只钻到这个深度(相机是 DCIM/100XXX 浅结构，够用)；
      - max_folders：找到这么多"含照片的文件夹"就停；
      - max_dirs：总共只遍历这么多个目录就停——防"一堆不含照片的杂目录"把 walk
        拖很久(max_folders 只在命中含照片目录时才生效，兜不住纯杂目录场景)。
    只统计 scanner 支持的扩展名(RAW+JPG/PNG/HEIC)。"""
    import os

    root = os.path.abspath(root)
    results = []
    root_depth = root.rstrip(os.sep).count(os.sep)
    dirs_seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirs_seen += 1
        if dirs_seen > max_dirs:
            break
        depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
        if depth >= max_depth:
            dirnames[:] = []  # 到达深度上限就不再往下钻
        count = 0
        size_bytes = 0
        for name in filenames:
            if os.path.splitext(name)[1].lower() in scanner.SUPPORTED_EXTENSIONS:
                count += 1
                try:
                    size_bytes += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        if count > 0:
            results.append({
                "path": dirpath,
                "name": os.path.basename(dirpath) or dirpath,
                "count": count,
                "size_mb": round(size_bytes / (1024 * 1024), 1),
            })
            if len(results) >= max_folders:
                break
    return results


class DeviceWatcher:
    """后台轮询可移动盘的插入。检测到"新出现"的盘就回调 on_card_inserted(drive)。

    基线在构造时就设为"当前已插着的盘"：所以 watcher 只上报"启动之后新插入"的卡，
    不会把开机时就插着的卡重复上报——那个场景由前端启动时调 detect_cards_now() 负责，
    两条路径职责不重叠(否则开机卡已在会弹两次窗)。daemon 线程，随主程序退出自动结束。"""

    def __init__(self, on_card_inserted, interval=2.0, list_fn=list_removable_drives):
        self._cb = on_card_inserted
        self._interval = interval
        self._list_fn = list_fn
        self._prev = set(list_fn())   # 基线=当前已插着的盘，只报之后新插入的
        self._stop = threading.Event()
        self._thread = None

    def poll_once(self):
        """扫一次，返回相对上次"新出现"的盘集合，并更新内部基线。可单测，不起线程。"""
        cur = set(self._list_fn())
        new = cur - self._prev
        self._prev = cur
        return new

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # 用 Event.wait 当可中断的 sleep：stop() 后能立刻退出，不用等满一个 interval
        while not self._stop.wait(self._interval):
            for drive in sorted(self.poll_once()):
                try:
                    self._cb(drive)
                except Exception:
                    # 单个盘回调失败(比如盘刚插上又被拔掉)不该打断整个监听线程
                    pass

    def stop(self):
        self._stop.set()
