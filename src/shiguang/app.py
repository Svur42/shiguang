from pathlib import Path

import webview

from . import db
from .api import THUMB_CACHE_DIR, Api
from .thumb_server import start_thumb_server

DB_PATH = Path.home() / ".shiguang" / "library.sqlite"
# Phase 2A 起入口页换成接入真实数据的完整原型 app.html（旧的极简验证页 index.html 保留备用）
FRONTEND_INDEX = Path(__file__).resolve().parent.parent.parent / "frontend" / "app.html"


def main():
    conn = db.connect(DB_PATH)
    # 缩略图服务器要服务这个目录，必须先确保它存在
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    thumb_base_url = start_thumb_server(THUMB_CACHE_DIR)
    api = Api(conn, thumb_base_url)
    webview.create_window(
        "拾光 ShiGuang",
        str(FRONTEND_INDEX),
        js_api=api,
        width=1200,
        height=800,
        frameless=True,  # 无边框：原型自带的标题栏就是真窗口顶部，避免套两层窗口/重复的系统边框
    )
    webview.start()
