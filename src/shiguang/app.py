from pathlib import Path

import webview

from . import db
from .api import THUMB_CACHE_DIR, Api
from .thumb_server import start_thumb_server

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path.home() / ".shiguang" / "library.sqlite"
# Phase 2A 起入口页换成接入真实数据的完整原型 app.html（旧的极简验证页 index.html 保留备用）
FRONTEND_INDEX = _PROJECT_ROOT / "frontend" / "app.html"
APP_ICON = _PROJECT_ROOT / "assets" / "shiguang.ico"


def _enable_native_window_behaviors(window):
    """无边框(frameless)窗口默认丢失了"最小化到任务栏的缩放动画"和系统菜单。
    原因：Windows 是根据窗口携带的样式位（WS_MINIMIZEBOX 等）来决定给不给动画/贴边的，
    frameless 把这些样式一起去掉了。这里在窗口显示前用 Win32 API 把这几个样式位加回来，
    能恢复最小化动画，同时不会带回可见的系统标题栏（那是 WS_CAPTION，我们没加）。
    包在 try 里：拿不到句柄或非 Windows 环境时静默跳过，绝不影响启动。"""

    def _apply(*args):
        try:
            import ctypes

            hwnd = int(window.native.Handle.ToInt32())
            GWL_STYLE = -16
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            user32.SetWindowLongW(
                hwnd, GWL_STYLE, style | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            )
            # 打印诊断：万一动画没恢复，能据此判断是"样式没加上"还是"加了但不够"
            print("[窗口样式] 已加回 WS_MINIMIZEBOX/MAXIMIZEBOX/SYSMENU，hwnd=", hwnd)
        except Exception as e:
            print("[窗口样式] 加样式失败（不影响使用）:", repr(e))

    try:
        window.events.before_show += _apply
    except Exception as e:
        print("[窗口样式] 无法挂 before_show 事件:", repr(e))


def main():
    conn = db.connect(DB_PATH)
    # 缩略图服务器要服务这个目录，必须先确保它存在
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    thumb_base_url = start_thumb_server(THUMB_CACHE_DIR)
    api = Api(conn, thumb_base_url)
    window = webview.create_window(
        "拾光 ShiGuang",
        str(FRONTEND_INDEX),
        js_api=api,
        width=1200,
        height=800,
        frameless=True,  # 无边框：原型自带的标题栏就是真窗口顶部，避免套两层窗口/重复的系统边框
    )
    _enable_native_window_behaviors(window)  # 无边框下用Win32样式位找回最小化动画
    # icon 取代任务栏/窗口的默认 Python 图标；文件不存在时不传，避免启动报错
    start_kwargs = {}
    if APP_ICON.exists():
        start_kwargs["icon"] = str(APP_ICON)
    webview.start(**start_kwargs)
