import os
import traceback
from pathlib import Path

import webview
from send2trash import send2trash

from . import db
from . import exif_read
from . import image_analysis
from . import raw_thumb
from . import scanner

# 缩略图磁盘缓存：list_photos() 之前是把每张缩略图编码成base64文字整个塞进返回值，
# 几百张RAW照片叠起来能到几十MB，传输和网页解析都会很慢、甚至让返回值变得不可靠。
# 现在改成"缩略图只写一次磁盘缓存文件、返回值只给一个 http 地址"，返回值体积从几十MB
# 降到几十KB量级；图片本体由本地缩略图HTTP服务器（thumb_server）按需提供，界面通过
# http://127.0.0.1:端口/{id}.jpg 加载（不能用 file:// 因为 WebView2 会拦截本地文件地址）。
SHIGUANG_HOME = Path.home() / ".shiguang"
THUMB_CACHE_DIR = SHIGUANG_HOME / "thumb_cache"
PREVIEW_CACHE_DIR = SHIGUANG_HOME / "preview_cache"
EXPO_CACHE_DIR = SHIGUANG_HOME / "expo_cache"


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
                thumbnail_url = f"{self.thumb_base_url}thumb_cache/{row['id']}.jpg"
            day, time = exif_read._format_day_time(row["capture_time"])
            photos.append(
                {
                    "id": row["id"],
                    "filename": row["filename"],
                    "name": row["filename"],
                    "thumbnail": thumbnail_url,
                    "tier": row["tier"],
                    "folder": row["folder"],
                    # 字段名必须与原型读取处一致：
                    # 原型详情面板读 p.cam/p.shutter/p.aperture/p.focal（不是camera）
                    "day": day,
                    "time": time,
                    "burst": None,
                    "iso": row["iso"],
                    "cam": row["cam"],
                    "shutter": row["shutter"],
                    "aperture": row["aperture"],
                    "focal": row["focal"],
                    "size": row["size"],
                }
            )
        return photos

    def get_preview(self, photo_id):
        """按需生成/返回 2560px 屏幕适配预览的URL，供全屏细看用（比512缩略图清晰）。
        已缓存则直接返回；没缓存则从原文件生成（RAW优先内嵌预览）；原文件不可访问则
        返回 url=None（前端继续用缩略图，不报错）。"""
        try:
            PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = PREVIEW_CACHE_DIR / f"{photo_id}.jpg"
            if not cache_file.exists():
                paths = db.get_paths_for_ids(self.conn, [photo_id])
                if not paths:
                    return {"url": None, "error": None}
                src = paths[0]
                if not os.path.exists(src):
                    return {"url": None, "error": None}
                data = raw_thumb.extract_thumbnail(src, max_size=2560)
                cache_file.write_bytes(data)
            return {"url": f"{self.thumb_base_url}preview_cache/{photo_id}.jpg", "error": None}
        except Exception:
            return {"url": None, "error": traceback.format_exc()}

    def open_external(self, photo_id):
        """用系统默认程序打开这张照片的原文件（一键调外部修图/看图软件）。
        原文件不可访问(卡拔了/移动了)则返回 opened=False，不报错。"""
        try:
            paths = db.get_paths_for_ids(self.conn, [photo_id])
            if not paths or not os.path.exists(paths[0]):
                return {"opened": False, "error": None}
            os.startfile(paths[0])  # Windows: 用关联的默认程序打开
            return {"opened": True, "error": None}
        except Exception:
            return {"opened": False, "error": traceback.format_exc()}

    def get_analysis(self, photo_id):
        """算详情面板真实数据：直方图(main/RGB)+过曝欠曝占比+高亮图URL。
        分析源优先2560预览缓存，没有则用导入时存的512缩略图BLOB；都没有则histograms=None。"""
        try:
            EXPO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            image_bytes = None
            preview_file = PREVIEW_CACHE_DIR / f"{photo_id}.jpg"
            # 尽量用2560高清预览做分析，这样过曝高亮图才清晰（不是糊的512）：
            # 预览还没生成、但原文件可访问时，先生成2560预览再分析
            if not preview_file.exists():
                paths = db.get_paths_for_ids(self.conn, [photo_id])
                if paths and os.path.exists(paths[0]):
                    try:
                        preview_file.parent.mkdir(parents=True, exist_ok=True)
                        preview_file.write_bytes(raw_thumb.extract_thumbnail(paths[0], max_size=2560))
                    except Exception:
                        pass
            if preview_file.exists():
                image_bytes = preview_file.read_bytes()
            if image_bytes is None:
                cur = self.conn.execute("SELECT thumbnail FROM photos WHERE id = ?", (photo_id,))
                row = cur.fetchone()
                if row and row["thumbnail"]:
                    image_bytes = row["thumbnail"]
            if image_bytes is None:
                return {"histograms": None, "over_pct": None, "under_pct": None,
                        "overlay_url": None, "error": None}

            hists = image_analysis.histograms(image_bytes)
            clip = image_analysis.clipping(image_bytes)
            overlay_file = EXPO_CACHE_DIR / f"{photo_id}.jpg"
            if not overlay_file.exists():
                overlay_file.write_bytes(image_analysis.make_overlay(image_bytes))

            return {
                "histograms": hists,
                "over_pct": clip["over_pct"],
                "under_pct": clip["under_pct"],
                "overlay_url": f"{self.thumb_base_url}expo_cache/{photo_id}.jpg",
                "error": None,
            }
        except Exception:
            return {"histograms": None, "over_pct": None, "under_pct": None,
                    "overlay_url": None, "error": traceback.format_exc()}

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

    def backfill_metadata(self):
        try:
            rows = db.list_photos(self.conn)
            # 只补"从没读过"的：read_metadata 至少能填 size，所以 size 仍为 NULL
            # 说明这张还没被补读过。避免 CR3/HEIC 这类读不出时间的每次启动都重读。
            targets = [r for r in rows if r["capture_time"] is None and r["size"] is None]
            updated = 0
            total = len(targets)
            for i, row in enumerate(targets, start=1):
                path = row["path"]
                if os.path.exists(path):
                    meta = exif_read.read_metadata(path)
                    db.update_metadata(self.conn, row["id"], meta)
                    if meta.get("capture_time"):
                        updated += 1
                try:
                    webview.windows[0].evaluate_js(
                        f"window.onBackfillProgress && window.onBackfillProgress({i}, {total})"
                    )
                except Exception:
                    pass
            return {"updated": updated, "photos": self.list_photos(), "error": None}
        except Exception:
            return {"updated": 0, "photos": self.list_photos(), "error": traceback.format_exc()}

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
