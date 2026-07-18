import traceback
from pathlib import Path

import webview

from . import db
from . import scanner

# 缩略图磁盘缓存：list_photos() 之前是把每张缩略图编码成base64文字整个塞进返回值，
# 几百张RAW照片叠起来能到几十MB，传输和网页解析都会很慢、甚至让返回值变得不可靠。
# 改成"缩略图只写一次磁盘缓存文件、返回值只给文件路径"之后，返回值体积从几十MB
# 降到几十KB量级（一条路径字符串通常远小于100字节）。
THUMB_CACHE_DIR = Path.home() / ".shiguang" / "thumb_cache"


class Api:
    def __init__(self, conn):
        self.conn = conn

    def list_photos(self):
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        photos = []
        for row in db.list_photos(self.conn):
            thumbnail_url = None
            if row["thumbnail"]:
                cache_file = THUMB_CACHE_DIR / f"{row['id']}.jpg"
                if not cache_file.exists():
                    cache_file.write_bytes(row["thumbnail"])
                thumbnail_url = cache_file.as_uri()
            photos.append(
                {
                    "id": row["id"],
                    "filename": row["filename"],
                    "thumbnail": thumbnail_url,
                    "tier": row["tier"],
                }
            )
        return photos

    def choose_folder_and_scan(self):
        try:
            result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return {"imported": 0, "photos": self.list_photos(), "error": None}
            folder = result[0]

            def report_progress(done, total):
                # 进度推送本身失败（比如窗口已关闭）不应该打断真正的导入工作。
                try:
                    webview.windows[0].evaluate_js(
                        f"window.onImportProgress && window.onImportProgress({done}, {total})"
                    )
                except Exception:
                    pass

            imported = scanner.scan_folder(self.conn, folder, progress_callback=report_progress)
            return {"imported": imported, "photos": self.list_photos(), "error": None}
        except Exception:
            # pywebview 在独立线程里调用这个方法，异常不会自动显示在界面上——
            # 必须显式捕获并把错误信息返回给前端，否则用户只会看到"点了没反应"。
            return {"imported": 0, "photos": self.list_photos(), "error": traceback.format_exc()}
