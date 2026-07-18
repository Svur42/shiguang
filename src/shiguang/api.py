import traceback
from pathlib import Path

import webview
from send2trash import send2trash

from . import db
from . import scanner

# 缩略图磁盘缓存：list_photos() 之前是把每张缩略图编码成base64文字整个塞进返回值，
# 几百张RAW照片叠起来能到几十MB，传输和网页解析都会很慢、甚至让返回值变得不可靠。
# 现在改成"缩略图只写一次磁盘缓存文件、返回值只给一个 http 地址"，返回值体积从几十MB
# 降到几十KB量级；图片本体由本地缩略图HTTP服务器（thumb_server）按需提供，界面通过
# http://127.0.0.1:端口/{id}.jpg 加载（不能用 file:// 因为 WebView2 会拦截本地文件地址）。
THUMB_CACHE_DIR = Path.home() / ".shiguang" / "thumb_cache"


class Api:
    def __init__(self, conn, thumb_base_url):
        self.conn = conn
        # thumb_base_url 形如 "http://127.0.0.1:53124/"，由 thumb_server 启动后提供
        self.thumb_base_url = thumb_base_url

    def list_photos(self):
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        photos = []
        for row in db.list_photos(self.conn):
            thumbnail_url = None
            if row["thumbnail"]:
                cache_file = THUMB_CACHE_DIR / f"{row['id']}.jpg"
                if not cache_file.exists():
                    cache_file.write_bytes(row["thumbnail"])
                thumbnail_url = f"{self.thumb_base_url}{row['id']}.jpg"
            photos.append(
                {
                    "id": row["id"],
                    "filename": row["filename"],
                    "name": row["filename"],
                    "thumbnail": thumbnail_url,
                    "tier": row["tier"],
                    "folder": row["folder"],
                    # 本阶段还没有EXIF/评分，占位给None。字段名必须与原型读取处一致：
                    # 原型详情面板读 p.cam/p.shutter/p.aperture/p.focal（不是camera）
                    "day": None,
                    "time": None,
                    "burst": None,
                    "iso": None,
                    "cam": None,
                    "shutter": None,
                    "aperture": None,
                    "focal": None,
                    "size": None,
                }
            )
        return photos

    # ── 窗口控制（无边框窗口下由前端标题栏按钮调用）──────────────
    def minimize_window(self):
        webview.windows[0].minimize()

    def toggle_maximize(self):
        win = webview.windows[0]
        if getattr(self, "_maximized", False):
            win.restore()
            self._maximized = False
        else:
            win.maximize()
            self._maximized = True

    def close_window(self):
        webview.windows[0].destroy()

    def set_tier(self, photo_id, tier):
        db.set_manual_tier(self.conn, photo_id, tier)
        return {"error": None}

    def list_folders(self):
        # name = 末级目录短名，供侧边栏显示，避免显示整条长路径
        folders = db.list_folders(self.conn)
        for f in folders:
            f["name"] = Path(f["folder"]).name or f["folder"]
        return folders

    def delete_photos(self, photo_ids):
        try:
            paths = db.get_paths_for_ids(self.conn, photo_ids)
            for path in paths:
                try:
                    send2trash(path)
                except OSError:
                    # 文件可能已经不在了（用户在别处删了/卡拔了）——不因单个文件失败
                    # 中断整批删除；数据库记录照常清掉，因为照片确实已经没了。
                    pass
            db.delete_photos(self.conn, photo_ids)
            return {"deleted": len(photo_ids), "error": None}
        except Exception:
            return {"deleted": 0, "error": traceback.format_exc()}

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
