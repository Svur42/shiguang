import json
from pathlib import Path

import webview

from . import db
from . import device_watch
from . import tray as tray_module
from .api import EXPO_CACHE_DIR, ORIG_CACHE_DIR, PREVIEW_CACHE_DIR, SHIGUANG_HOME, THUMB_CACHE_DIR, Api
from .thumb_server import start_thumb_server

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path.home() / ".shiguang" / "library.sqlite"


def _clear_caches():
    """关软件时清空所有图像磁盘缓存(缩略图/预览/过曝图/原图)，只保留 library.sqlite
    这份"记忆"(评价/EXIF/旋转/卡记忆)。用户明确要的"关闭删缓存、留数据"。代价：下次
    重开要重新生成缩略图(原文件可访问的会现场生成，拔卡的显示占位)。"""
    for cache_dir in (THUMB_CACHE_DIR, PREVIEW_CACHE_DIR, EXPO_CACHE_DIR, ORIG_CACHE_DIR):
        try:
            for f in cache_dir.glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass
        except OSError:
            pass
# Phase 2A 起入口页换成接入真实数据的完整原型 app.html（旧的极简验证页 index.html 保留备用）
FRONTEND_INDEX = _PROJECT_ROOT / "frontend" / "app.html"
IMPORT_WINDOW_INDEX = _PROJECT_ROOT / "frontend" / "import_window.html"
APP_ICON = _PROJECT_ROOT / "assets" / "shiguang.ico"
INSTANCE_FILE = Path.home() / ".shiguang" / ".instance"   # 记录当前实例的HTTP端口，供单实例激活用
_MUTEX_NAME = "Global\\ShiGuang_SingleInstance_Mutex"


def _acquire_single_instance():
    """单实例锁：用 Windows 命名互斥锁。返回 (handle, already_running)。
    already_running=True 表示已经有一个拾光在跑——新进程别再开一个(否则托盘会多个图标)。
    非 Windows 或取锁失败则当作"没有已运行实例"，不阻断启动。"""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        already = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        return handle, already
    except Exception:
        return None, False


def _activate_existing_instance():
    """已有实例在跑时，让那个实例把窗口显示到前台(而不是新开一个)。
    读 .instance 里记的端口，GET 它的 /__activate__ 触发显示。失败就安静放弃。"""
    try:
        import urllib.request
        port = INSTANCE_FILE.read_text(encoding="utf-8").strip()
        urllib.request.urlopen(f"http://127.0.0.1:{port}/__activate__", timeout=2).read()
    except Exception:
        pass


def main():
    # 单实例：已经有一个拾光在跑就别再开(否则系统托盘会出现多个相同图标)——激活已有那个
    # 的窗口，然后本进程直接退出。
    _mutex_handle, already_running = _acquire_single_instance()
    if already_running:
        _activate_existing_instance()
        return

    conn = db.connect(DB_PATH)
    # 静态服务器服务 ~/.shiguang 根目录，下含 thumb_cache 与 preview_cache 两子目录，
    # 必须先确保它们都存在
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    EXPO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ORIG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # generator holder：服务器请求缺失缩略图时按需生成。api 在服务器之后才建，用一个
    # 可变字典桥接——服务器启动时拿到的是这个闭包，api 建好后把真正的实现填进 holder。
    gen_holder = {"fn": None}
    activate_holder = {"fn": None}   # 单实例激活：新进程GET /__activate__ 时把窗口拉前台
    thumb_base_url = start_thumb_server(
        SHIGUANG_HOME,
        generator=lambda rel: gen_holder["fn"](rel) if gen_holder["fn"] else None,
        on_activate=lambda: activate_holder["fn"]() if activate_holder["fn"] else None,
    )
    # 把本实例的端口写进 .instance，另一个新进程据此激活它、然后自己退出
    try:
        INSTANCE_FILE.write_text(thumb_base_url.rstrip("/").rsplit(":", 1)[-1], encoding="utf-8")
    except OSError:
        pass
    api = Api(conn, thumb_base_url)
    gen_holder["fn"] = api.ensure_cache_file
    # 卡插着时回填老数据的 is_card，让加列前导入的SD卡文件夹能出现在侧边栏(一次即永久)
    api.backfill_card_flags()
    # 认卡+重绑：若当前插着的卡换了盘符(E:→F:)，把它记忆里的照片路径重绑到当前盘符，
    # 让第一次 list_folders 就按当前盘符找到记忆文件夹(主线程执行，早于 webview 起窗)。
    api.sync_all_inserted_cards()
    window = webview.create_window(
        "拾光 ShiGuang",
        str(FRONTEND_INDEX),
        js_api=api,
        width=1200,
        height=800,
        frameless=True,  # 无边框：原型自带的标题栏就是真窗口顶部，避免套两层窗口/重复的系统边框
    )
    # 独立小导入窗：启动就建好但隐藏，托盘挂机插卡时只显示它(不打扰主窗)，确认导入后
    # 才显示主窗。启动就建(而非插卡时才建)是为了避开"从后台线程创建窗口"的脆弱性。
    import_window = webview.create_window(
        "导入存储卡",
        str(IMPORT_WINDOW_INDEX),
        js_api=api,
        width=460,
        height=560,
        frameless=True,
        hidden=True,
        on_top=True,
    )

    watcher = None
    tray_icon = None
    # main_hidden: 主窗当前是否隐藏(缩托盘/最小化)——插卡通知要用：已记忆的卡不弹窗打扰，
    # 但主窗看不见时侧边栏刷新用户也看不见，这时才需要弹小窗告知"已识别"(见下 present_card)。
    state = {"quitting": False, "tray_ok": False, "main_hidden": False}

    def show_window():
        # 从托盘/最小化恢复：显示 + 还原到前台
        try:
            window.show()
            window.restore()
            state["main_hidden"] = False
        except Exception:
            pass

    def hide_or_minimize():
        """最小化：有托盘就隐藏到托盘；没托盘(起不来)就退回普通任务栏最小化——
        绝不让窗口"隐藏了却没有托盘图标可点回来"，那会变成用户最怕的"窗口回不来"。"""
        try:
            if state["tray_ok"]:
                window.hide()
            else:
                window.minimize()
            state["main_hidden"] = True
            return True
        except Exception:
            return False

    def do_quit():
        """干净退出序列：先立"真要退了"标志(让 closing 拦截放行)，**立刻清缓存**，再停
        后台线程、停托盘、销毁窗口。

        清缓存提前到这里、不再只放在 webview.start() 的 finally 里，是因为发现了真实
        bug：do_quit 常常是从**非GUI线程**触发的(托盘图标点"退出"=pystray自己的后台线程；
        标题栏X按钮走的是前端JS→js_api派发线程)。跨线程调用 window.destroy() 在某些环境
        下可能静默失败(被下面的 except 吞掉)，导致事件循环不退、webview.start() 永不返回、
        finally 里的清缓存永远执行不到——用户反馈"有些方式退出缓存没清"正是这个。
        现在"决定要退出"这一刻就清缓存，不依赖窗口销毁是否真的成功、事件循环是否真的退出。
        finally 里仍保留一次清缓存作为兜底(清空目录后再清一次是空操作，无副作用)。
        防重入 + 顺序很关键，否则易残留关不掉的后台进程。"""
        if state["quitting"]:
            return
        state["quitting"] = True
        # 退出前把还在"5秒撤销倒计时"里、没真正提交的删除立刻执行完：否则真退出后JS
        # 随窗口一起销毁，那些延迟提交的删除(delete_photos/forget_photos)从未真正调用，
        # 数据库里其实没删，下次打开又"复活"。等前端确认flush完成，最多等3秒——给个
        # 上限防止极端情况(JS已损坏/窗口不可用)把关闭动作拖到卡死，好过偶尔复活。
        # do_quit 在此处不会是在GUI消息循环线程上同步阻塞：JS触发的退出经js_api派发到
        # 后台线程，托盘退出在pystray自己的线程；唯一在GUI线程同步调用do_quit的路径
        # (on_closing的兜底分支)是JS已经不可用时才走到，evaluate_js会直接抛异常，
        # 根本不会走到 event.wait()，故无死锁风险。
        try:
            event = api.prepare_quit_flush()
            window.evaluate_js(
                "(window.flushPendingDeletes ? window.flushPendingDeletes() : Promise.resolve())"
                ".then(() => window.pywebview.api.confirm_flush_done())"
                ".catch(() => window.pywebview.api.confirm_flush_done())"
            )
            event.wait(timeout=3)
        except Exception:
            pass
        _clear_caches()
        if watcher:
            watcher.stop()
        if tray_icon:
            tray_icon.stop()
        try:
            import_window.destroy()   # 小窗也要销毁，否则它的事件循环会拖住进程不退
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            pass

    def on_closing():
        # 统一关闭行为：任务栏关闭/Alt+F4/系统关闭 都和点自定义X按钮一样，弹前端"退出还是
        # 缩托盘"确认框(记住过选择则直接执行)，而不是直接缩托盘。取消这次原生关闭、交给
        # 前端确认框决定 quit/hide。主动退出(do_quit已置标志)时放行。
        if state["quitting"]:
            return True
        try:
            window.evaluate_js("window.handleCloseRequest && window.handleCloseRequest()")
            return False
        except Exception:
            # 前端不可用兜底：先试缩起来；连缩都失败才真退出。
            # 这里改走 do_quit()(而不是直接 return True 放行原生关闭)——原来只放行原生关闭，
            # 只会关掉当前这个主窗口，隐藏的小导入窗、watcher/托盘线程都没人管，事件循环
            # 不会真的退出、finally 里的清缓存也执行不到，是"某些情况下缓存不清"的另一个真因。
            # do_quit() 会清缓存+停线程+销毁两个窗口，一步到位；返回 False 是因为退出交给
            # do_quit 自己做，不需要再让这次原生 close 重复处理。
            if hide_or_minimize():
                return False
            do_quit()
            return False

    window.events.closing += on_closing
    api.set_window_handlers(hide=hide_or_minimize, show=show_window, quit=do_quit,
                             is_hidden=lambda: state["main_hidden"])
    activate_holder["fn"] = show_window   # 另一个新进程来敲 /__activate__ 时，把本窗口拉到前台

    def show_import():
        try:
            import_window.show()
        except Exception:
            pass

    def hide_import():
        try:
            import_window.hide()
        except Exception:
            pass

    def refresh_main():
        # 导入完成后让主窗重新拉照片并重绘
        try:
            window.evaluate_js("window.reloadPhotos && window.reloadPhotos()")
        except Exception:
            pass

    def push_import_progress(done, total):
        # 把导入进度推给小导入窗显示"已导入 X/共 Y 张"
        try:
            import_window.evaluate_js(
                f"window.onImportProgress && window.onImportProgress({int(done)}, {int(total)})"
            )
        except Exception:
            pass

    def present_card(info):
        """把检测到的一张卡呈现出来：只弹独立小导入窗，主窗不动。
        小窗不可用时兜底退回"主窗+内嵌弹框"，功能不丢。运行时插卡和启动时卡已插着
        两条路径都走这里，行为一致。info["mode"]:
          "confirm" = 有新文件夹待确认(folders 非空，原有行为)；
          "known"   = 卡全认识、无需确认，只在主窗隐藏时弹出告知"已识别"(folders 为空，
                      不能再用"folders 非空"当早退判据，否则这条通知永远发不出去)。"""
        if not info:
            return
        if info.get("mode") != "known" and not info.get("folders"):
            return
        api._pending_card = info
        payload = json.dumps(info, ensure_ascii=False)
        try:
            import_window.evaluate_js(f"window.renderCard && window.renderCard({payload})")
            import_window.show()
            return
        except Exception:
            pass
        show_window()
        try:
            window.evaluate_js(f"window.onCardDetected && window.onCardDetected({payload})")
        except Exception:
            pass

    api.set_import_window_handlers(
        show_import=show_import, hide_import=hide_import,
        show_main=show_window, refresh_main=refresh_main,
        push_progress=push_import_progress, present_card=present_card,
    )

    # 后台监听插卡：认卡+重绑→刷新侧边栏(记忆文件夹自动出现)→只把"新发现"的文件夹弹小窗
    # 让用户确认。已记忆的文件夹不重复弹。handle_card_inserted 内部用 _present_card/_refresh_main
    # 句柄完成呈现，这里只负责触发。
    def on_card_inserted(drive):
        try:
            api.handle_card_inserted(drive)
        except Exception:
            pass

    watcher = device_watch.DeviceWatcher(on_card_inserted)
    watcher.start()

    # 系统托盘：软件最小化到托盘后仍常驻后台。托盘起不来(无桌面等)不阻断程序，但要记下
    # tray_ok=False，好让"最小化"降级成任务栏最小化、前端也据此决定弹不弹关闭确认框。
    tray_icon = tray_module.TrayIcon(
        on_show=show_window,
        on_quit=do_quit,
        icon_path=APP_ICON if APP_ICON.exists() else None,
    )
    state["tray_ok"] = bool(tray_icon.start())
    api.set_tray_available(state["tray_ok"])

    # icon 取代任务栏/窗口的默认 Python 图标；文件不存在时不传，避免启动报错
    start_kwargs = {}
    if APP_ICON.exists():
        start_kwargs["icon"] = str(APP_ICON)
    try:
        webview.start(**start_kwargs)
    finally:
        watcher.stop()
        tray_icon.stop()
        # 幂等兜底：确保两个窗口都销毁——只要还有一个窗口活着，事件循环就不退、进程不退。
        for w in (import_window, window):
            try:
                w.destroy()
            except Exception:
                pass
        _clear_caches()   # 关软件清缩略图等图像缓存，只留 library.sqlite（用户决策）
        try:
            INSTANCE_FILE.unlink()   # 清掉单实例端口文件
        except OSError:
            pass
