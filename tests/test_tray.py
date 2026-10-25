from shiguang import tray


def test_load_icon_fallback_when_path_missing():
    img = tray._load_icon_image("/nonexistent/nope.ico")
    assert img.size == (64, 64)   # 兜底纯色方块


def test_load_icon_fallback_when_path_none():
    img = tray._load_icon_image(None)
    assert img.size == (64, 64)


class _FakeIcon:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_tray_show_handler_invokes_callback():
    shown = []
    t = tray.TrayIcon(on_show=lambda: shown.append(1), on_quit=lambda: None, icon_path=None)
    t._handle_show(_FakeIcon(), None)
    assert shown == [1]


def test_tray_quit_handler_runs_callback_then_stops_icon():
    order = []
    t = tray.TrayIcon(on_show=lambda: None, on_quit=lambda: order.append("quit"), icon_path=None)
    fake = _FakeIcon()
    t._handle_quit(fake, None)
    assert order == ["quit"]       # 先执行应用退出序列
    assert fake.stopped is True    # 再停托盘自身


def test_tray_handlers_swallow_callback_errors():
    """回调抛异常不应让托盘菜单处理崩溃(否则托盘线程死掉)。"""
    def boom():
        raise RuntimeError("炸了")
    t = tray.TrayIcon(on_show=boom, on_quit=boom, icon_path=None)
    fake = _FakeIcon()
    t._handle_show(fake, None)     # 不抛
    t._handle_quit(fake, None)     # 不抛，且仍停了图标
    assert fake.stopped is True
