from pathlib import Path

import webview

from . import db
from .api import PREVIEW_CACHE_DIR, SHIGUANG_HOME, THUMB_CACHE_DIR, Api
from .thumb_server import start_thumb_server

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path.home() / ".shiguang" / "library.sqlite"
# Phase 2A 起入口页换成接入真实数据的完整原型 app.html（旧的极简验证页 index.html 保留备用）
FRONTEND_INDEX = _PROJECT_ROOT / "frontend" / "app.html"
APP_ICON = _PROJECT_ROOT / "assets" / "shiguang.ico"


def main():
    conn = db.connect(DB_PATH)
    # 静态服务器服务 ~/.shiguang 根目录，下含 thumb_cache 与 preview_cache 两子目录，
    # 必须先确保它们都存在
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    thumb_base_url = start_thumb_server(SHIGUANG_HOME)
    api = Api(conn, thumb_base_url)
    webview.create_window(
        "拾光 ShiGuang",
        str(FRONTEND_INDEX),
        js_api=api,
        width=1200,
        height=800,
        frameless=True,  # 无边框：原型自带的标题栏就是真窗口顶部，避免套两层窗口/重复的系统边框
    )
    # icon 取代任务栏/窗口的默认 Python 图标；文件不存在时不传，避免启动报错
    start_kwargs = {}
    if APP_ICON.exists():
        start_kwargs["icon"] = str(APP_ICON)
    webview.start(**start_kwargs)
