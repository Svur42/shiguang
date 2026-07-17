from pathlib import Path

import webview

from . import db
from .api import Api

DB_PATH = Path.home() / ".shiguang" / "library.sqlite"
FRONTEND_INDEX = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"


def main():
    conn = db.connect(DB_PATH)
    api = Api(conn)
    webview.create_window(
        "拾光 ShiGuang",
        str(FRONTEND_INDEX),
        js_api=api,
        width=1000,
        height=700,
    )
    webview.start()
