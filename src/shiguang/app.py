from pathlib import Path

import webview

from . import db
from .api import THUMB_CACHE_DIR, Api
from .thumb_server import start_thumb_server

DB_PATH = Path.home() / ".shiguang" / "library.sqlite"
FRONTEND_INDEX = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"


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
        width=1000,
        height=700,
    )
    webview.start()
