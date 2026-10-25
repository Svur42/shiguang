import os
import threading
import traceback
from pathlib import Path

import webview
from send2trash import send2trash

from . import db
from . import dedup
from . import device_watch
from . import exif_read
from . import image_analysis
from . import raw_thumb
from . import scanner
from . import scoring

# 缩略图磁盘缓存：数据库(记忆)只存路径/编号/标签/EXIF这些数据，不永久保存任何图像
# 字节——图片本体只作为磁盘缓存文件存在，删了能重建(有原文件时)、原文件不在时就
# 显示不出来，这是用户明确要的"只存数据不存图"。返回值给前端的是 http 地址（不能用
# file:// 因为 WebView2 会拦截本地文件地址），图片本体由本地HTTP服务器（thumb_server）
# 按需提供，界面通过 http://127.0.0.1:端口/{id}.jpg 加载。
SHIGUANG_HOME = Path.home() / ".shiguang"
THUMB_CACHE_DIR = SHIGUANG_HOME / "thumb_cache"
PREVIEW_CACHE_DIR = SHIGUANG_HOME / "preview_cache"
EXPO_CACHE_DIR = SHIGUANG_HOME / "expo_cache"
ORIG_CACHE_DIR = SHIGUANG_HOME / "orig_cache"


class Api:
    def __init__(self, conn, thumb_base_url):
        self.conn = conn
        # thumb_base_url 形如 "http://127.0.0.1:53124/"，由 thumb_server 启动后提供
        self.thumb_base_url = thumb_base_url
        # DB 写并发锁：插卡认卡(rebind)跑在 watcher 后台线程，与 pywebview 派发到 JS 线程的
        # list_photos/import/analyze 等共用同一个 check_same_thread=False 的 sqlite 连接。
        # 单连接跨线程并发使用不安全，用一把可重入锁串行化所有 DB 访问(RLock 容忍方法内
        # 互相调用，如 import_folders→list_photos)。
        self._db_lock = threading.RLock()
        # 退出前flush延迟删除用：do_quit 通知前端把"还在5秒撤销倒计时"的删除立刻提交完，
        # 完成后前端回调 confirm_flush_done() 设置这个事件，do_quit 才继续真正销毁窗口。
        self._flush_done_event = threading.Event()

    def prepare_quit_flush(self):
        """do_quit 退出前调用：重置事件并返回，供它 wait() 等前端确认flush完成。"""
        self._flush_done_event = threading.Event()
        return self._flush_done_event

    def confirm_flush_done(self):
        """前端 flushPendingDeletes() 跑完后回调，唤醒 do_quit 里等待的线程。"""
        self._flush_done_event.set()

    def _thumb_cache_path(self, photo_id, path):
        """确保这张照片的512缩略图缓存文件存在，返回其 Path；不存在时尝试从原文件
        现场生成(数据库不再存图像字节，缓存是唯一来源)；缓存没有、原文件也不可访问
        (拔卡+缓存已被清)则返回 None——调用方据此显示占位/跳过分析，不报错。

        `{id}.failed` 是负缓存标记：原文件确实解不出缩略图(损坏/不支持的格式)时打上，
        避免 list_photos/analyze_all 每次调用都对同一张必然失败的照片重新解码一次——
        这类文件内容不会变，重试没有意义，只会拖慢大库的刷新速度。"""
        cache_file = THUMB_CACHE_DIR / f"{photo_id}.jpg"
        if cache_file.exists():
            return cache_file
        fail_marker = THUMB_CACHE_DIR / f"{photo_id}.failed"
        if fail_marker.exists():
            return None
        if not path or not os.path.exists(path):
            return None
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(raw_thumb.extract_thumbnail(path))
            return cache_file
        except Exception:
            try:
                fail_marker.touch()
            except OSError:
                pass
            return None

    def ensure_cache_file(self, relpath):
        """供本地HTTP服务器按需调用：请求 thumb_cache/{id}.jpg 或 preview_cache/{id}.jpg
        但文件不存在时，现场从原图生成。原文件不可访问则不生成(服务器返回404→前端占位)。
        这样 list_photos 不必同步生成上千张(秒开)，缩略图随浏览器请求(懒加载只请求可见的)
        即时补齐。"""
        try:
            rel = str(relpath).replace("\\", "/").strip("/")
            parts = rel.split("/")
            if len(parts) != 2 or not parts[1].endswith(".jpg"):
                return
            kind, name = parts
            try:
                pid = int(name[:-4])
            except ValueError:
                return
            with self._db_lock:   # 与 watcher 线程认卡写库互斥(本方法跑在 HTTP 服务器线程)
                paths = db.get_paths_for_ids(self.conn, [pid])
            src = paths[0] if paths else None
            if kind == "thumb_cache":
                self._thumb_cache_path(pid, src)   # 内部：缺则从原图生成512缩略图
            elif kind == "preview_cache":
                pf = PREVIEW_CACHE_DIR / name
                if not pf.exists() and src and os.path.exists(src):
                    pf.parent.mkdir(parents=True, exist_ok=True)
                    pf.write_bytes(raw_thumb.extract_thumbnail(src, max_size=2560))
        except Exception:
            pass

    def list_photos(self):
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        photos = []
        with self._db_lock:   # 读一次性取出(与插卡认卡写库互斥)，后面纯做文件/字段处理不占锁
            rows = db.list_photos(self.conn)
        for row in rows:
            # 只列"能显示"的照片：有缩略图缓存、或原文件可访问(能按需生成)。两者都没有
            # (拔卡了 + 缓存又被清空)的照片根本显示不出内容，就别在界面上留一排白格子——
            # 记录仍在库里(记忆保留)，插回卡/缓存回来了自然又会出现。
            if not (THUMB_CACHE_DIR / f"{row['id']}.jpg").exists() and not os.path.exists(row["path"]):
                continue
            # 直接给确定性URL，不在这里同步生成(否则清缓存后重开要现场生成上千张、卡死)。
            # 缩略图由服务器在浏览器请求时按需生成(ensure_cache_file)。
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
                    "rotation": row["rotation"],
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
                with self._db_lock:   # 与 watcher 认卡写库互斥
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

    def get_original(self, photo_id):
        """按需生成/返回接近原始分辨率的大图URL，供全屏放大到高倍时看清细节(检查对焦)。
        比 2560 预览更清晰但更大更慢，所以只在用户真的放大某张时才调。已缓存直接返回；
        原文件不可访问则 url=None(前端继续用2560预览，不报错)。"""
        try:
            ORIG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = ORIG_CACHE_DIR / f"{photo_id}.jpg"
            if not cache_file.exists():
                with self._db_lock:   # 与 watcher 认卡写库互斥
                    paths = db.get_paths_for_ids(self.conn, [photo_id])
                if not paths or not os.path.exists(paths[0]):
                    return {"url": None, "error": None}
                cache_file.write_bytes(raw_thumb.extract_full(paths[0]))
            return {"url": f"{self.thumb_base_url}orig_cache/{photo_id}.jpg", "error": None}
        except Exception:
            return {"url": None, "error": traceback.format_exc()}

    def open_external(self, photo_id):
        """用系统默认程序打开这张照片的原文件（一键调外部修图/看图软件）。
        原文件不可访问(卡拔了/移动了)则返回 opened=False，不报错。"""
        try:
            with self._db_lock:   # 与 watcher 认卡写库互斥
                paths = db.get_paths_for_ids(self.conn, [photo_id])
            if not paths or not os.path.exists(paths[0]):
                return {"opened": False, "error": None}
            os.startfile(paths[0])  # Windows: 用关联的默认程序打开
            return {"opened": True, "error": None}
        except Exception:
            return {"opened": False, "error": traceback.format_exc()}

    def get_analysis(self, photo_id):
        """算详情面板真实数据：直方图(main/RGB)+过曝欠曝占比+高亮图URL。
        分析源优先2560预览缓存，没有则退到512缩略图缓存(数据库不存图像字节，缓存是
        唯一来源)；都没有(拔卡+缓存也清了)则histograms=None。"""
        try:
            EXPO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            image_bytes = None
            preview_file = PREVIEW_CACHE_DIR / f"{photo_id}.jpg"
            with self._db_lock:   # 与 watcher 认卡写库互斥
                paths = db.get_paths_for_ids(self.conn, [photo_id])
            path = paths[0] if paths else None
            # 尽量用2560高清预览做分析，这样过曝高亮图才清晰（不是糊的512）：
            # 预览还没生成、但原文件可访问时，先生成2560预览再分析
            if not preview_file.exists() and path and os.path.exists(path):
                try:
                    preview_file.parent.mkdir(parents=True, exist_ok=True)
                    preview_file.write_bytes(raw_thumb.extract_thumbnail(path, max_size=2560))
                except Exception:
                    pass
            if preview_file.exists():
                image_bytes = preview_file.read_bytes()
            if image_bytes is None:
                cache_file = self._thumb_cache_path(photo_id, path)
                if cache_file:
                    image_bytes = cache_file.read_bytes()
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

    # ── 托盘挂机相关（app.py 在建窗后注入真正的实现）──────────────
    def set_window_handlers(self, hide=None, show=None, quit=None, is_hidden=None):
        self._hide_handler = hide
        self._show_handler = show
        self._quit_handler = quit
        self._is_hidden_handler = is_hidden   # 主窗当前是否隐藏(缩到托盘/最小化)，插卡通知要用

    def _main_window_hidden(self):
        try:
            return bool(self._is_hidden_handler and self._is_hidden_handler())
        except Exception:
            return False

    def set_tray_available(self, ok):
        self._tray_ok = bool(ok)

    def tray_available(self):
        """前端据此决定：托盘不可用时，"记住的最小化"不能静默执行(否则窗口回不来)，
        应仍弹关闭确认框让用户能选"退出"，且把"最小化到托盘"讲清是缩到任务栏。"""
        return bool(getattr(self, "_tray_ok", False))

    def hide_to_tray(self):
        """最小化：有托盘→隐藏到托盘；无托盘→app.py 的 handler 会降级成任务栏最小化。
        进程继续在后台跑(插卡检测不停)。"""
        h = getattr(self, "_hide_handler", None)
        if h:
            h()
        return {"error": None}

    def quit_app(self):
        """真正退出：走 app.py 注入的干净退出序列(停 watcher→停托盘→销毁窗口)。"""
        q = getattr(self, "_quit_handler", None)
        if q:
            q()
        return {"error": None}

    def rotate_photo(self, photo_id, delta):
        """把某张照片的显示旋转角 +delta 度(顺时针+90/逆时针-90)并持久化，返回新角度。
        只改显示方向、不动原文件；网格缩略图和全屏都按这个角度旋转显示。"""
        try:
            with self._db_lock:
                rows = self.conn.execute(
                    "SELECT rotation FROM photos WHERE id = ?", (photo_id,)
                ).fetchone()
                cur = rows["rotation"] if rows else 0
                new = (int(cur) + int(delta)) % 360
                db.set_rotation(self.conn, photo_id, new)
            return {"rotation": new, "error": None}
        except Exception:
            return {"rotation": 0, "error": traceback.format_exc()}

    def set_tier(self, photo_id, tier):
        with self._db_lock:
            db.set_manual_tier(self.conn, photo_id, tier)
        return {"error": None}

    @staticmethod
    def _drive_of(path):
        # 取路径所在盘符，归一成大写 'E:'(无尾斜杠)；无盘符(如 '/card/A')返回 ''
        return os.path.splitdrive(os.path.abspath(path))[0].upper()

    def _current_card_map(self):
        """扫当前所有可移动盘，读各自卷序列号，返回:
          - serial_to_drive: {序列号大写: 盘符'E:'}，只含"唯一序列号"的盘(能精确认卡的)；
          - removable_drives: 当前可移动盘符集合 {'E:', 'F:'}(不管读不读得到序列号)；
          - ambiguous_or_unknown: 序列号读不到、或多盘同序列号(克隆卡)的盘符集合——
            这些盘无法用序列号精确认卡，list_folders 对它们降级成"盘符+存在性"判定(H1/M1)。
        序列号读一次缓存进 drive_serial(同一盘符只读一次，省慢速读卡器的重复 stat)。"""
        try:
            removable = [os.path.splitdrive(r)[0].upper() for r in device_watch.list_removable_drives()]
        except Exception:
            return None  # 判不了盘符(非Windows等)：调用方退回"只按 is_card 全显"
        removable_drives = set(removable)
        serial_by_drive = {}
        for d in removable_drives:
            serial_by_drive[d] = device_watch.read_volume_serial(d + "\\")
        # 统计每个序列号出现在几个盘上：>1 = 克隆卡/重复序列号 → 不可靠
        counts = {}
        for s in serial_by_drive.values():
            if s:
                counts[s] = counts.get(s, 0) + 1
        serial_to_drive = {}
        ambiguous_or_unknown = set()
        for d, s in serial_by_drive.items():
            if not s or counts.get(s, 0) > 1:
                ambiguous_or_unknown.add(d)  # 读不到序列号 或 与别的盘同序列号
            else:
                serial_to_drive[s] = d
        return {
            "serial_to_drive": serial_to_drive,
            "removable_drives": removable_drives,
            "ambiguous_or_unknown": ambiguous_or_unknown,
        }

    def list_folders(self):
        """侧边栏 = 当前插着的这张卡上、当前仍存在的文件夹。
        判定逻辑(依赖插卡时已 rebind 把当前卡的路径持久化到当前盘符，故此处一律用持久化
        路径，不做临时重建——避免"侧边栏说有、点开却按旧路径找不到"的分叉):
          对每个 is_card=1 的文件夹 F(盘符 Dstored、序列号 S)：
          1) F 所在盘符当前不是可移动盘 → 不显示(卡已拔/换了别的盘);
          2) 文件夹在卡上已被删/改名(isdir False) → 不显示(用户要的);
          3) 序列号能精确认卡：S 就是当前 Dstored 盘的序列号 → 显示；
             S 是别的卡(当前 Dstored 上插的是不同序列号的卡) → 不显示(区分物理卡);
          4) 降级(H1/M1)：S 为空(老数据)、或当前 Dstored 盘序列号读不到/克隆卡 →
             无法精确认卡，退回"盘符可移动 + 存在"即显示，绝不因序列号临时读不到而让
             照片凭空消失。"""
        info = self._current_card_map()   # 只读设备(无DB访问)：不占 DB 锁，免慢速读卡器阻塞其它DB操作
        with self._db_lock:
            folders = db.list_folders(self.conn)
            local_folders = db.list_local_folders(self.conn)
        if info is None:
            # 判不了盘符：不过滤，只按 is_card 全显(非Windows/异常兜底)
            for f in folders:
                f["name"] = Path(f["folder"]).name or f["folder"]
                f["kind"] = "card"
            for f in local_folders:
                f["name"] = Path(f["folder"]).name or f["folder"]
                f["kind"] = "local"
            return folders + local_folders
        removable = info["removable_drives"]
        serial_to_drive = info["serial_to_drive"]
        degrade_drives = info["ambiguous_or_unknown"]
        result = []
        for f in folders:
            folder = f["folder"]
            drive = self._drive_of(folder)
            if drive not in removable:
                continue                                  # (1) 卡不在
            if not os.path.isdir(folder):
                continue                                  # (2) 文件夹已删/改名
            fserial = f.get("card_serial")
            if fserial and fserial in serial_to_drive:
                if serial_to_drive[fserial] != drive:
                    continue                              # (3) 这是同序列号但……不可能到这(唯一)；保险
                # 精确命中当前这张卡
            elif fserial and drive not in degrade_drives:
                # (3) 有序列号、当前盘序列号也读到了且是别的卡 → 不是这张卡
                continue
            # else: (4) 降级显示(老数据无序列号 / 序列号读不到 / 克隆卡)
            f["name"] = Path(folder).name or folder
            f["kind"] = "card"
            result.append(f)
        # 本地(非SD卡)文件夹：不进SD卡记忆、插卡不自动加载，但导入后也在侧边栏显示——
        # 只要文件夹当前还存在就显示(本地盘一直在，不受"卡插着"约束)。标 kind=local 供前端区分。
        for f in local_folders:
            folder = f["folder"]
            if not os.path.isdir(folder):
                continue   # 本地文件夹被删/移走 → 不显示
            f["name"] = Path(folder).name or folder
            f["kind"] = "local"
            result.append(f)
        return result

    def list_stacks(self):
        """给前端堆叠视图：把已分析(有phash)且当前可显示的照片分成连拍/相似组。
        返回 [{id, memberIds(最锐在前), cover, burst, similar}]，只含>=2张的组；无/出错返回[]。
        只纳入"能显示"的照片(有缓存或原文件在)，与 list_photos 过滤一致，免堆叠里含拔卡幽灵成员。"""
        try:
            with self._db_lock:
                rows = db.list_for_grouping(self.conn)
            items = []
            for r in rows:
                if not ((THUMB_CACHE_DIR / f"{r['id']}.jpg").exists() or os.path.exists(r["path"])):
                    continue
                items.append({
                    "id": r["id"], "capture_time": r["capture_time"], "cam": r["cam"],
                    "phash": r["phash"], "focus_score": r["focus_score"],
                })
            return dedup.group_stacks(items)
        except Exception:
            return []

    def backfill_phash(self):
        """给"已分析过但还没算感知哈希"的老照片补算 dhash(相似/连拍堆叠要用)。
        只补 phash、**不碰 tier**(不覆盖用户改判)；从512缩略图缓存算(有缓存/原文件可访问即可)。
        堆叠需要 phash，而 phash 只在"开始分析"时给未分析照片算——已分析的老数据靠这个补上，
        否则导入的旧照片永远分不出连拍/相似组。返回补了多少张。"""
        try:
            with self._db_lock:
                rows = db.list_missing_phash(self.conn)
            updated = 0
            for row in rows:
                cache_file = self._thumb_cache_path(row["id"], row["path"])
                if not cache_file:
                    continue   # 不可显示(拔卡+无缓存)→跳过，插回卡再补
                try:
                    ph = dedup.dhash(cache_file.read_bytes())
                except Exception:
                    continue
                with self._db_lock:
                    db.set_phash(self.conn, row["id"], ph)
                updated += 1
            return {"updated": updated, "error": None}
        except Exception:
            return {"updated": 0, "error": traceback.format_exc()}

    def backfill_card_flags(self):
        """回填老数据的 is_card：加 is_card 列之前导入的照片默认都是0，会被侧边栏
        (只显is_card=1)漏掉。这里把"文件夹盘符当前是可移动盘"的老记录标成卡来源
        (一次标记、永久保留)——卡插着重开时自动补上，用户无需手动重新导入。
        本地固定盘的文件夹判不出可移动→保持0→不进侧边栏(正是用户要的)。"""
        try:
            roots = {os.path.splitdrive(r)[0].upper() for r in device_watch.list_removable_drives()}
            if not roots:
                return {"updated": 0, "error": None}
            with self._db_lock:
                folders = [r["folder"] for r in
                           self.conn.execute("SELECT DISTINCT folder FROM photos WHERE is_card = 0")]
                updated = 0
                for folder in folders:
                    drive = os.path.splitdrive(os.path.abspath(folder))[0].upper()
                    if drive in roots:
                        self.conn.execute("UPDATE photos SET is_card = 1 WHERE folder = ?", (folder,))
                        updated += 1
                self.conn.commit()
            return {"updated": updated, "error": None}
        except Exception:
            return {"updated": 0, "error": traceback.format_exc()}

    def _folder_is_card(self, folder):
        """判断这个文件夹是不是在可移动卡(SD等)上——决定要不要进侧边栏文件夹记忆。
        用当前可移动盘列表比对文件夹所在盘符；卡拔了/判不了就当作非卡(不记)。"""
        try:
            drive = os.path.splitdrive(os.path.abspath(folder))[0].upper()
            roots = {os.path.splitdrive(r)[0].upper() for r in device_watch.list_removable_drives()}
            return 1 if drive in roots else 0
        except Exception:
            return 0

    def _folder_card_serial(self, folder):
        """读这个文件夹所在盘(卡)的卷序列号，导入时随照片存库，供日后认卡用；读不到返回 None。"""
        try:
            drive = os.path.splitdrive(os.path.abspath(folder))[0]
            if not drive:
                return None
            return device_watch.read_volume_serial(drive + "\\")
        except Exception:
            return None

    @staticmethod
    def _folder_tail(folder):
        # 去盘符+归一化(大小写不敏感、去尾分隔符)，用来跨盘符/大小写比对"是不是同一个文件夹"
        tail = os.path.splitdrive(os.path.abspath(folder))[1]
        return os.path.normcase(os.path.normpath(tail))

    def sync_card_paths_for_drive(self, drive):
        """插卡入口调用：读这张卡的序列号；若库里记得这张卡(同序列号)但记录还停在旧盘符，
        就把它所有照片的 path/folder 重绑到当前盘符(之后一切读路径统一用持久化路径)。
        返回该卡序列号(None 表示读不到/无法认卡)。跑在 watcher 后台线程，加锁与 JS 线程互斥。"""
        serial = device_watch.read_volume_serial(
            (os.path.splitdrive(drive)[0] or drive) + "\\"
        )
        if not serial:
            return None
        cur_drive = os.path.splitdrive(drive)[0].upper()
        with self._db_lock:
            # 只有当这张卡的记录还停在别的盘符时才重绑(同盘符不动)
            stored_drives = {self._drive_of(f) for f in db.folders_for_serial(self.conn, serial)}
            if stored_drives and stored_drives != {cur_drive}:
                db.rebind_card_paths(self.conn, serial, cur_drive)
        return serial

    def sync_all_inserted_cards(self):
        """启动时(主线程)对当前每一张插着的卡认卡+重绑，让第一次 list_folders 就看到
        正确盘符的记忆文件夹，不必等前端插卡回调。"""
        try:
            for drive in device_watch.list_removable_drives():
                self.sync_card_paths_for_drive(drive)
        except Exception:
            pass
        return {"error": None}

    def _split_new_folders(self, drive, serial):
        """扫这张卡上含照片的文件夹，分成"已记忆(该卡序列号记过的)"和"新发现"。
        新发现的才需要弹小导入窗让用户确认(已记忆的靠 list_folders 自动显示，不重复弹)。
        比对按去盘符+大小写归一，避免同一文件夹因盘符/大小写差异被误判成新的。
        find_photo_folders(磁盘遍历,慢)在锁外做,只对 DB 查询持短临界区(免长时间占 DB 锁)。"""
        found = device_watch.find_photo_folders(drive)   # 慢速磁盘遍历：不占 DB 锁
        if not serial:
            return found  # 认不出的卡：全部当新发现，让用户确认
        with self._db_lock:
            remembered_raw = db.folders_for_serial(self.conn, serial)
        remembered = {self._folder_tail(f) for f in remembered_raw}
        return [f for f in found if self._folder_tail(f["path"]) not in remembered]

    def handle_card_inserted(self, drive):
        """插卡统一入口(运行时 watcher 插卡 / 启动已插着 都走这里)：
          1) 认卡+重绑(sync)——让已记忆文件夹按当前盘符持久化；
          2) 刷新主窗侧边栏——认得的卡的记忆文件夹立刻出现(即使没有新文件夹也刷新)；
          3) 有"新发现、没记忆过"的文件夹→弹小导入窗让用户确认导入。
          4) 没有新文件夹(这张卡全认识)但**主窗当前隐藏(缩托盘/最小化)**→仍弹一下小窗
             告知"已识别，无需操作"(不然挂托盘时插拔卡毫无反馈，用户会以为没检测到——
             真机反馈的bug：托盘挂机时拔卡重插同一张已导入过的卡，弹窗一直不出现)。
             主窗可见时不弹(侧边栏刷新用户看得见，弹窗是多余打扰)。
        返回给调用方 {folders: 新发现的} 便于测试。"""
        try:
            serial = self.sync_card_paths_for_drive(drive)
            new_folders = self._split_new_folders(drive, serial)   # 内部自管短临界区
            # 认得的卡：记忆文件夹已可显示，刷新侧边栏(reloadPhotos 会同时刷文件夹)
            if getattr(self, "_refresh_main", None):
                self._refresh_main()
            if new_folders:
                info = {
                    "drive": drive,
                    "folders": new_folders,
                    "total_count": sum(f["count"] for f in new_folders),
                    "total_size_mb": round(sum(f["size_mb"] for f in new_folders), 1),
                    "mode": "confirm",
                    "error": None,
                }
                self._pending_card = info
                if getattr(self, "_present_card", None):
                    self._present_card(info)
                return info
            if self._main_window_hidden():
                with self._db_lock:
                    known_count = len(db.folders_for_serial(self.conn, serial)) if serial else 0
                if getattr(self, "_present_card", None):
                    self._present_card({"drive": drive, "folders": [], "mode": "known",
                                         "known_count": known_count, "error": None})
            return {"drive": drive, "folders": [], "total_count": 0, "total_size_mb": 0, "error": None}
        except Exception:
            return {"drive": drive, "folders": [], "total_count": 0,
                    "total_size_mb": 0, "error": traceback.format_exc()}

    def _purge_cache_files(self, photo_ids):
        # 数据库不存图像字节，图像数据全在这几个磁盘缓存里——删记录时必须连带清缓存，
        # 否则缓存文件变成永久留在磁盘的孤儿文件。
        for photo_id in photo_ids:
            for cache_dir in (THUMB_CACHE_DIR, PREVIEW_CACHE_DIR, EXPO_CACHE_DIR, ORIG_CACHE_DIR):
                for cache_file in (cache_dir / f"{photo_id}.jpg", cache_dir / f"{photo_id}.failed"):
                    try:
                        cache_file.unlink()
                    except FileNotFoundError:
                        pass

    def delete_photos(self, photo_ids):
        try:
            with self._db_lock:
                paths = db.get_paths_for_ids(self.conn, photo_ids)
            for path in paths:
                try:
                    send2trash(path)
                except OSError:
                    # 文件可能已经不在了（用户在别处删了/卡拔了）——不因单个文件失败
                    # 中断整批删除；数据库记录照常清掉，因为照片确实已经没了。
                    pass
            self._purge_cache_files(photo_ids)
            with self._db_lock:
                db.delete_photos(self.conn, photo_ids)
            return {"deleted": len(photo_ids), "error": None}
        except Exception:
            return {"deleted": 0, "error": traceback.format_exc()}

    def forget_photos(self, photo_ids):
        """从相册移除指定的一批照片(按id)：删数据库记录 + 清缓存，但**不删原始照片
        文件**(可能在SD卡上，整批 send2trash 太危险)。用户要的是"从软件里看不到"。
        按 id 而非按文件夹路径删——这样删除范围锁死在用户 swipe 当时看到的那批，不会
        误删这之后又重新导入到同名文件夹的照片(延迟提交窗口内的竞态)。"""
        try:
            ids = list(photo_ids or [])
            self._purge_cache_files(ids)
            with self._db_lock:
                db.delete_photos(self.conn, ids)
            return {"removed": len(ids), "photos": self.list_photos(), "error": None}
        except Exception:
            return {"removed": 0, "photos": self.list_photos(), "error": traceback.format_exc()}

    def forget_folder(self, folder):
        """按文件夹路径移除(便捷入口，内部转按id)。注意延迟提交场景优先用 forget_photos
        传当时捕获的 id，避免误删提交窗口内新导入的同名文件夹照片。"""
        with self._db_lock:
            ids = db.get_ids_for_folder(self.conn, folder)
        return self.forget_photos(ids)

    def backfill_metadata(self):
        try:
            with self._db_lock:
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
                    with self._db_lock:
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

    def needs_analysis_count(self):
        """待(重新)分析的张数：未定档 或 缺感知哈希(旧数据)——但**只数当前可显示的**
        (有缓存或原文件可访问)。否则拔卡时库里上千条不可访问的记录会让计数虚高、分析按钮
        亮着却点了也没用(analyze 对不可访问的照片本就跳过)。与 analyze_all 实际能处理的集合一致。"""
        try:
            with self._db_lock:
                rows = db.list_needs_analysis(self.conn)
            count = sum(
                1 for r in rows
                if (THUMB_CACHE_DIR / f"{r['id']}.jpg").exists() or os.path.exists(r["path"])
            )
            return {"count": count, "error": None}
        except Exception:
            return {"count": 0, "error": traceback.format_exc()}

    def analyze_all(self):
        """「开始分析」：对"未定档(tier IS NULL) 或 缺感知哈希(phash IS NULL，旧数据)"的照片跑
        P0 评分，写 auto_tier/tier + phash + focus_score。评分读512缩略图缓存(有就读，没有且原文件
        可访问就现场生成)；原文件不可访问且无缓存的跳过(留待插回卡)。ISO 喂噪点自适应。每张推进度，
        单张失败不打断整批。
        旧数据(已定档但缺phash)：补 phash/focus_score，并用**新模型**重评档位——但用户手动改过的
        (tier!=auto_tier)保留不覆盖。这样旧库点一次"分析"就能出堆叠 + 用上新评分模型。"""
        try:
            with self._db_lock:
                rows = db.list_needs_analysis(self.conn)
            total = len(rows)
            analyzed = 0
            for i, row in enumerate(rows, start=1):
                cache_file = self._thumb_cache_path(row["id"], row["path"])
                if cache_file:
                    try:
                        image_bytes = cache_file.read_bytes()
                        result = scoring.score_image_bytes(image_bytes, iso=row["iso"])
                        # 顺带算感知哈希(相似/连拍堆叠用)+ 取主体锐度分(堆叠选封面/排序用)——
                        # 同一趟已解码的缩略图上做，不额外解码。哈希失败不影响评分入库。
                        try:
                            ph = dedup.dhash(image_bytes)
                        except Exception:
                            ph = None
                        fscore = result["metrics"].get("subject_vol")
                        # 已定档且被用户手动改过(tier!=auto_tier)→保留其档位，只补phash/focus+刷auto_tier；
                        # 其余(从未分析 / 分析过但没手动改)→用新模型重评档位。
                        # 用户设定的档要保留：tier 有值且 != auto_tier(含分析前手动改的,
                        # 那时 auto_tier 为 NULL；也含分析后覆盖的)。仅当 tier==auto_tier
                        # (算法自己的判定、用户没动)才用新模型重评。
                        manual = row["tier"] is not None and row["tier"] != row["auto_tier"]
                        with self._db_lock:
                            db.set_analysis(self.conn, row["id"], result["tier"],
                                            phash=ph, focus_score=fscore, keep_tier=manual)
                        analyzed += 1
                    except Exception:
                        # 单张评分失败(缩略图损坏等)跳过，不中断整批，也不改它的档
                        pass
                try:
                    webview.windows[0].evaluate_js(
                        f"window.onAnalyzeProgress && window.onAnalyzeProgress({i}, {total})"
                    )
                except Exception:
                    pass
            return {"analyzed": analyzed, "photos": self.list_photos(), "error": None}
        except Exception:
            return {"analyzed": 0, "photos": self.list_photos(), "error": traceback.format_exc()}

    # ── 独立小导入窗（托盘挂机插卡时只弹这个小窗，确认后才显主窗）──────────
    def set_import_window_handlers(self, show_import=None, hide_import=None,
                                   show_main=None, refresh_main=None, push_progress=None,
                                   present_card=None):
        self._show_import = show_import
        self._hide_import = hide_import
        self._show_main = show_main
        self._refresh_main = refresh_main
        self._push_progress = push_progress
        self._present_card = present_card

    def popup_cards_now(self):
        """前端启动时调一次：当前插着的卡认卡+重绑后，只把"新发现(没记忆过)"的文件夹
        合并弹一个独立小导入窗；已记忆的文件夹靠 list_folders 自动出现在侧边栏、不重复弹。
        覆盖"开软件时卡已经插着"的场景(后台 watcher 只报启动后新插入的)。"""
        try:
            all_new = []
            for drive in device_watch.list_removable_drives():
                serial = self.sync_card_paths_for_drive(drive)
                all_new.extend(self._split_new_folders(drive, serial))   # 内部自管短临界区
            if all_new:
                merged = {
                    "folders": all_new,
                    "total_count": sum(f["count"] for f in all_new),
                    "total_size_mb": round(sum(f["size_mb"] for f in all_new), 1),
                }
                self._pending_card = merged
                if getattr(self, "_present_card", None):
                    self._present_card(merged)
            return {"error": None}
        except Exception:
            return {"error": traceback.format_exc()}

    def get_pending_card(self):
        """小导入窗加载时来取"当前检测到的这张卡"的文件夹清单。"""
        return getattr(self, "_pending_card", None) or {"folders": []}

    def cancel_import(self):
        """小导入窗点取消/好的：关掉小窗 + 弹出主窗。
        早前设计是"取消只关小窗、主窗仍留在托盘"，但真机反馈体验不好——弹窗处理完(不管是
        确认导入、不导入、还是只是「已识别」的告知)，用户都该能看到主界面，不用自己去
        系统托盘里手动点开。跟 import_and_finish(确认导入)行为对齐，只是不跑导入。"""
        h = getattr(self, "_hide_import", None)
        if h:
            h()
        s = getattr(self, "_show_main", None)
        if s:
            s()
        return {"error": None}

    def import_and_finish(self, folder_paths):
        """小导入窗点确认：导入所选文件夹(带进度推送到小窗) → 关小窗 → 显示主窗 →
        刷新主窗照片。这样"插卡先弹小窗、确认后才弹大窗"。"""
        try:
            push = getattr(self, "_push_progress", None)
            result = self.import_folders(folder_paths, progress_callback=push)
            if getattr(self, "_hide_import", None):
                self._hide_import()
            if getattr(self, "_show_main", None):
                self._show_main()
            if getattr(self, "_refresh_main", None):
                self._refresh_main()
            return result
        except Exception:
            return {"imported": 0, "photos": self.list_photos(), "error": traceback.format_exc()}

    def scan_card_folders(self, drive):
        """扫描一张卡(盘根)里含照片的文件夹，返回给前端弹窗渲染用的结构。
        folders 为空表示这盘里没照片(比如空U盘)——调用方据此决定不弹窗。"""
        try:
            folders = device_watch.find_photo_folders(drive)
            total_count = sum(f["count"] for f in folders)
            total_size_mb = round(sum(f["size_mb"] for f in folders), 1)
            return {
                "drive": drive,
                "folders": folders,
                "total_count": total_count,
                "total_size_mb": total_size_mb,
                "error": None,
            }
        except Exception:
            return {"drive": drive, "folders": [], "total_count": 0,
                    "total_size_mb": 0, "error": traceback.format_exc()}

    def detect_cards_now(self):
        """前端启动时主动拉一次：现在插着的可移动卡(且盘里有照片的)有哪些。
        覆盖"开软件时卡已经插着"的场景(后台 watcher 只推送启动后新插入的)。"""
        try:
            cards = []
            for drive in device_watch.list_removable_drives():
                info = self.scan_card_folders(drive)
                if info["folders"]:  # 只报真的有照片的卡，空盘不打扰
                    cards.append(info)
            return {"cards": cards, "error": None}
        except Exception:
            return {"cards": [], "error": traceback.format_exc()}

    def import_folders(self, folder_paths, progress_callback=None):
        """导入用户勾选的一批文件夹(可多选)。每个文件夹走和手动导入同一套 scanner，
        缩略图直接写磁盘缓存不进库。单个文件夹失败不打断整批。
        progress_callback(done, total)：跨所有文件夹的全局进度(供小导入窗显示 X/共Y张)。"""
        try:
            folders = list(folder_paths or [])
            total = sum(scanner.count_supported(f) for f in folders) if progress_callback else 0
            base = [0]  # 已处理累计(用list让内层闭包能改)

            def make_cb():
                if not progress_callback:
                    return None

                def cb(done_in_folder, total_in_folder):
                    try:
                        progress_callback(base[0] + done_in_folder, total)
                    except Exception:
                        pass
                return cb

            imported = 0
            for folder in folders:
                n = scanner.count_supported(folder) if progress_callback else 0
                is_card = self._folder_is_card(folder)          # 读盘/序列号(慢)在锁外算
                card_serial = self._folder_card_serial(folder)
                try:
                    # db_lock 传给 scanner：只在每张的 DB 读写瞬间持锁，解码不占锁
                    imported += scanner.scan_folder(
                        self.conn, folder, thumb_cache_dir=THUMB_CACHE_DIR,
                        progress_callback=make_cb(), is_card=is_card,
                        card_serial=card_serial, db_lock=self._db_lock,
                    )
                except Exception:
                    # 某个文件夹扫描失败(权限/卡被拔)不该让其他已选文件夹也白导
                    pass
                base[0] += n
            return {"imported": imported, "photos": self.list_photos(), "error": None}
        except Exception:
            return {"imported": 0, "photos": self.list_photos(), "error": traceback.format_exc()}

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

            is_card = self._folder_is_card(folder)          # 读盘/序列号(慢)在锁外算
            card_serial = self._folder_card_serial(folder)
            imported = scanner.scan_folder(
                self.conn, folder, thumb_cache_dir=THUMB_CACHE_DIR,
                progress_callback=report_progress, is_card=is_card,
                card_serial=card_serial, db_lock=self._db_lock,   # DB 读写瞬间才持锁
            )
            return {"imported": imported, "photos": self.list_photos(), "error": None}
        except Exception:
            # pywebview 在独立线程里调用这个方法，异常不会自动显示在界面上——
            # 必须显式捕获并把错误信息返回给前端，否则用户只会看到"点了没反应"。
            return {"imported": 0, "photos": self.list_photos(), "error": traceback.format_exc()}
