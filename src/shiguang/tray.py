"""Windows 系统托盘图标（通知区域）。用 pystray 在后台线程跑，与 pywebview 的
主线程 GUI 循环并存。

作用：软件"最小化到托盘"后仍常驻后台(插卡检测继续工作)，托盘图标可点开恢复窗口、
右键可真正退出。退出序列必须干净(停 watcher→停托盘→销毁窗口)，否则会残留关不掉的
后台进程(用户很在意的"幽灵进程")。托盘功能无法 headless 自测，需真机验证。
"""
import pystray
from PIL import Image


def _load_icon_image(icon_path):
    """加载托盘图标图像。图标文件不存在时用一个纯色小方块兜底，保证托盘一定能显示。"""
    try:
        if icon_path and str(icon_path):
            return Image.open(str(icon_path))
    except Exception:
        pass
    return Image.new("RGB", (64, 64), (43, 108, 176))  # 兜底：品牌蓝方块


class TrayIcon:
    def __init__(self, on_show, on_quit, icon_path=None, title="拾光 ShiGuang"):
        self._on_show = on_show
        self._on_quit = on_quit
        image = _load_icon_image(icon_path)
        menu = pystray.Menu(
            # default=True：左键点击图标即触发"显示拾光"
            pystray.MenuItem("显示拾光", self._handle_show, default=True),
            pystray.MenuItem("退出", self._handle_quit),
        )
        self._icon = pystray.Icon("shiguang", image, title, menu)

    def _handle_show(self, icon, item):
        try:
            self._on_show()
        except Exception:
            pass

    def _handle_quit(self, icon, item):
        # 先执行应用的退出序列(停 watcher/销毁窗口)，再停托盘自身
        try:
            self._on_quit()
        except Exception:
            pass
        try:
            icon.stop()
        except Exception:
            pass

    def start(self):
        """在独立线程运行托盘(run_detached)，不阻塞主线程的 pywebview GUI 循环。
        托盘启动失败(无桌面会话等)不应让整个程序崩溃——降级为"没有托盘"，软件照常用。"""
        try:
            self._icon.run_detached()
            return True
        except Exception:
            return False

    def stop(self):
        try:
            self._icon.stop()
        except Exception:
            pass
