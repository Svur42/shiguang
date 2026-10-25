import io
import os

from PIL import Image

import shiguang.api as api_module
import shiguang.db as db
from shiguang.api import Api


THUMB_BASE_URL = "http://127.0.0.1:59999/"


def _use_isolated_thumb_cache(monkeypatch, tmp_path):
    """避免测试往真实的 ~/.shiguang/thumb_cache 写文件、也避免不同测试之间
    因为照片id重复（每个测试都是从id=1开始）而互相污染缓存内容。"""
    cache_dir = tmp_path / "thumb_cache"
    monkeypatch.setattr(api_module, "THUMB_CACHE_DIR", cache_dir)
    return cache_dir


def _make_api(conn):
    return Api(conn, THUMB_BASE_URL)


def _write_jpeg(path, color=(128, 128, 128), size=(64, 64)):
    Image.new("RGB", size, color).save(path)


def _jpeg_bytes(color=(128, 128, 128), size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_list_photos_regenerates_cache_from_original_file(tmp_path, monkeypatch):
    """数据库不存图像字节：缓存不存在但原文件可访问时，应从原文件现场生成缓存。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "a.jpg"
    _write_jpeg(real)
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="a.jpg")
    api = _make_api(conn)

    photos = api.list_photos()

    assert len(photos) == 1
    assert photos[0]["filename"] == "a.jpg"
    # list_photos 只给确定性URL、不再同步生成(否则清缓存后重开要现场生成上千张卡死)；
    # 不能是 file:// —— WebView2 会拦截本地文件地址导致图片显示为受损
    assert photos[0]["thumbnail"] == f"{THUMB_BASE_URL}thumb_cache/{photo_id}.jpg"
    # 缩略图改由服务器按需生成：ensure_cache_file 被请求时才从原图生成
    assert not (cache_dir / f"{photo_id}.jpg").exists()   # list_photos 没生成
    api.ensure_cache_file(f"thumb_cache/{photo_id}.jpg")
    assert (cache_dir / f"{photo_id}.jpg").exists()        # 按需生成成功


def test_list_photos_uses_existing_cache_file_even_when_original_missing(tmp_path, monkeypatch):
    """核心场景：原文件不可访问(卡拔了)，但缓存文件还在——照样能显示，不需要原文件。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path="/gone/a.jpg", folder="/gone", filename="a.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{photo_id}.jpg").write_bytes(b"\xff\xd8\xff-fake-jpeg-bytes")
    api = _make_api(conn)

    photos = api.list_photos()

    assert photos[0]["thumbnail"] == f"{THUMB_BASE_URL}thumb_cache/{photo_id}.jpg"
    assert (cache_dir / f"{photo_id}.jpg").read_bytes() == b"\xff\xd8\xff-fake-jpeg-bytes"


def test_list_photos_does_not_rewrite_existing_cache_file(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path="/gone/a.jpg", folder="/gone", filename="a.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{photo_id}.jpg").write_bytes(b"original-bytes")
    api = _make_api(conn)

    api.list_photos()
    # 手动改一下缓存文件内容，再调用一次list_photos，验证它不会覆盖已存在的缓存
    (cache_dir / f"{photo_id}.jpg").write_bytes(b"manually-modified")
    api.list_photos()

    assert (cache_dir / f"{photo_id}.jpg").read_bytes() == b"manually-modified"


def test_list_photos_hides_unshowable_photos(tmp_path, monkeypatch):
    """原文件不可访问 且 缓存也不存在(卡拔了+缓存被清了)：这张根本显示不出内容，
    list_photos 不列出它(界面不留一排白格子)；记录仍在库里(记忆保留)。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path="/fake/broken.jpg", folder="/fake", filename="broken.jpg")
    api = _make_api(conn)

    assert api.list_photos() == []                         # 不可显示→不列出
    assert len(db.list_photos(conn)) == 1                  # 但库记录还在(记忆保留)

    # 一旦缓存回来了(比如插回卡按需生成过)，又会正常列出
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{photo_id}.jpg").write_bytes(b"x")
    assert len(api.list_photos()) == 1


class _FakeWindow:
    """测试用的假pywebview窗口。默认文件夹对话框返回值和evaluate_js记录方式
    由各测试通过构造参数定制，避免每个测试都要重新声明整个类。"""

    def __init__(self, dialog_result):
        self._dialog_result = dialog_result
        self.evaluate_js_calls = []

    def create_file_dialog(self, dialog_type):
        if isinstance(self._dialog_result, Exception):
            raise self._dialog_result
        return self._dialog_result

    def evaluate_js(self, script):
        self.evaluate_js_calls.append(script)


def test_choose_folder_and_scan_imports_photos(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    _write_jpeg(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    fake_window = _FakeWindow(dialog_result=[str(tmp_path)])
    monkeypatch.setattr("webview.windows", [fake_window])

    result = api.choose_folder_and_scan()

    assert result["imported"] == 1
    assert len(result["photos"]) == 1
    assert result["error"] is None


def test_choose_folder_and_scan_generates_thumbnail_on_demand_not_at_import(tmp_path, monkeypatch):
    """导入不再在导入时解码缩略图(提速)；缩略图按需生成——ensure_cache_file 被请求时才写。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    _write_jpeg(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    monkeypatch.setattr("webview.windows", [_FakeWindow(dialog_result=[str(tmp_path)])])

    result = api.choose_folder_and_scan()

    photo_id = result["photos"][0]["id"]
    assert not (cache_dir / f"{photo_id}.jpg").exists()    # 导入时不写(按需生成)
    api.ensure_cache_file(f"thumb_cache/{photo_id}.jpg")
    assert (cache_dir / f"{photo_id}.jpg").exists()        # 按需请求时才生成


def test_choose_folder_and_scan_pushes_progress_via_evaluate_js(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    _write_jpeg(tmp_path / "a.jpg")
    _write_jpeg(tmp_path / "b.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    fake_window = _FakeWindow(dialog_result=[str(tmp_path)])
    monkeypatch.setattr("webview.windows", [fake_window])

    api.choose_folder_and_scan()

    assert len(fake_window.evaluate_js_calls) == 2
    assert "onImportProgress(1, 2)" in fake_window.evaluate_js_calls[0]
    assert "onImportProgress(2, 2)" in fake_window.evaluate_js_calls[1]


def test_choose_folder_and_scan_handles_cancelled_dialog(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    fake_window = _FakeWindow(dialog_result=None)
    monkeypatch.setattr("webview.windows", [fake_window])

    result = api.choose_folder_and_scan()

    assert result["imported"] == 0
    assert result["error"] is None


def test_choose_folder_and_scan_from_background_thread_does_not_crash(tmp_path, monkeypatch):
    """回归测试：pywebview真实环境下，js_api方法是在独立于主线程的后台线程被调用的。
    之前 db.connect() 没传 check_same_thread=False 时，这个场景会抛
    sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread。
    这里在主线程建连接、在另一个线程调用，模拟真实场景。"""
    import threading

    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    _write_jpeg(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")  # 主线程创建
    api = _make_api(conn)

    fake_window = _FakeWindow(dialog_result=[str(tmp_path)])
    monkeypatch.setattr("webview.windows", [fake_window])

    outcome = {}

    def call_from_background_thread():
        outcome["result"] = api.choose_folder_and_scan()

    thread = threading.Thread(target=call_from_background_thread)
    thread.start()
    thread.join()

    assert outcome["result"]["error"] is None
    assert outcome["result"]["imported"] == 1


def test_choose_folder_and_scan_returns_error_field_instead_of_raising(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    fake_window = _FakeWindow(dialog_result=RuntimeError("模拟对话框炸了"))
    monkeypatch.setattr("webview.windows", [fake_window])

    result = api.choose_folder_and_scan()

    assert result["error"] is not None
    assert "RuntimeError" in result["error"]


def test_list_photos_includes_folder_and_placeholder_fields(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path="/card/A/x.jpg", folder="/card/A", filename="x.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True); (cache_dir / f"{pid}.jpg").write_bytes(b"x")
    api = _make_api(conn)

    p = api.list_photos()[0]

    # 字段名必须和原型读取处一致：原型读 p.cam / p.shutter / p.aperture / p.focal
    assert p["folder"] == "/card/A"
    assert p["tier"] is None
    for key in ("day", "time", "burst", "iso", "cam", "shutter", "aperture", "focal", "size"):
        assert key in p


def test_set_tier_persists(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True); (cache_dir / f"{pid}.jpg").write_bytes(b"x")
    api = _make_api(conn)
    photo_id = api.list_photos()[0]["id"]

    api.set_tier(photo_id, "fix")

    assert api.list_photos()[0]["tier"] == "fix"


def test_list_folders_returns_only_card_folders(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    # list_folders 现在要求文件夹真实存在(isdir)，用真实目录
    card_a = tmp_path / "cardA"; card_a.mkdir()
    card_b = tmp_path / "cardB"; card_b.mkdir()
    local = tmp_path / "local"; local.mkdir()
    db.insert_photo(conn, path=str(card_a / "1.jpg"), folder=str(card_a), filename="1.jpg", is_card=1)
    db.insert_photo(conn, path=str(card_b / "2.jpg"), folder=str(card_b), filename="2.jpg", is_card=1)
    db.insert_photo(conn, path=str(local / "x.jpg"), folder=str(local), filename="x.jpg", is_card=0)
    api = _make_api(conn)
    # tmp_path 所在盘当前"插着"(可移动)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [drive])

    folders = api.list_folders()

    # 侧边栏现在 SD卡(kind=card) 和 本地(kind=local) 都显示，用 kind 区分(本地不进SD卡记忆但要显示)
    by_kind = {f["folder"]: f["kind"] for f in folders}
    assert by_kind == {str(card_a): "card", str(card_b): "card", str(local): "local"}


def test_list_folders_hides_card_folders_when_card_unplugged(tmp_path, monkeypatch):
    """卡曾导入过(is_card=1)但当前拔了 → 侧边栏不显示该文件夹(记录仍在库)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="E:/card/A/1.jpg", folder="E:/card/A", filename="1.jpg", is_card=1)
    api = _make_api(conn)
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [])  # 没插任何卡

    assert api.list_folders() == []                       # 侧边栏空
    assert len(db.list_folders(conn)) == 1                # 但库里记录还在


def test_list_folders_hides_folder_deleted_on_card(tmp_path, monkeypatch):
    """卡插着(序列号匹配)但记忆里的文件夹在卡上已被删/改名(isdir False) → 不显示。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    gone = tmp_path / "gone"   # 故意不 mkdir，模拟卡上已删
    db.insert_photo(conn, path=str(gone / "1.jpg"), folder=str(gone),
                    filename="1.jpg", is_card=1, card_serial="AAAA1111")
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [drive])
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "AAAA1111")

    assert api.list_folders() == []                       # 文件夹不在卡上 → 不显示


def test_list_folders_hides_when_different_card_same_letter(tmp_path, monkeypatch):
    """同一盘符插的是"另一张卡"(序列号不同) → 不显示旧卡的记忆文件夹(区分物理卡)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    folder = tmp_path / "DCIM"; folder.mkdir()   # 目录真实存在(碰巧同结构)
    db.insert_photo(conn, path=str(folder / "1.jpg"), folder=str(folder),
                    filename="1.jpg", is_card=1, card_serial="OLDCARD0")
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [drive])
    # 当前这张卡序列号是 NEWCARD1，与记忆里的 OLDCARD0 不同
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "NEWCARD1")

    assert api.list_folders() == []                       # 是另一张卡 → 不显示旧卡文件夹


def test_list_folders_degrades_when_serial_unreadable(tmp_path, monkeypatch):
    """卡插着、文件夹在，但这次序列号读不到(慢速读卡器抖动) → 降级按盘符显示，不消失(H1)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    folder = tmp_path / "DCIM"; folder.mkdir()
    db.insert_photo(conn, path=str(folder / "1.jpg"), folder=str(folder),
                    filename="1.jpg", is_card=1, card_serial="AAAA1111")
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [drive])
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: None)

    assert {f["folder"] for f in api.list_folders()} == {str(folder)}   # 序列号读不到也照常显示


def test_delete_photos_moves_files_to_trash_and_removes_rows(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real_file = tmp_path / "real.jpg"
    real_file.write_bytes(b"content")
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real_file), folder=str(tmp_path), filename="real.jpg")
    api = _make_api(conn)
    photo_id = api.list_photos()[0]["id"]

    trashed = []
    monkeypatch.setattr("shiguang.api.send2trash", lambda p: trashed.append(p))

    result = api.delete_photos([photo_id])

    assert result["deleted"] == 1
    assert result["error"] is None
    assert trashed == [str(real_file)]
    assert api.list_photos() == []


def test_delete_photos_removes_cache_files(tmp_path, monkeypatch):
    """删除照片必须连带清掉三处缓存文件，否则数据库不存图之后，图像数据就变成
    永远删不掉的孤儿文件——这正是本次"只存数据不存图"改动想解决的问题。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    preview_dir = tmp_path / "preview_cache"
    expo_dir = tmp_path / "expo_cache"
    monkeypatch.setattr(api_module, "PREVIEW_CACHE_DIR", preview_dir)
    monkeypatch.setattr(api_module, "EXPO_CACHE_DIR", expo_dir)
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path="/gone/a.jpg", folder="/gone", filename="a.jpg")
    for d in (cache_dir, preview_dir, expo_dir):
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{photo_id}.jpg").write_bytes(b"x")
    (cache_dir / f"{photo_id}.failed").touch()
    api = _make_api(conn)
    monkeypatch.setattr("shiguang.api.send2trash", lambda p: None)

    result = api.delete_photos([photo_id])

    assert result["error"] is None
    for d in (cache_dir, preview_dir, expo_dir):
        assert not (d / f"{photo_id}.jpg").exists()
    assert not (cache_dir / f"{photo_id}.failed").exists()


def test_analyze_all_does_not_retry_photo_marked_as_failed(tmp_path, monkeypatch):
    """负缓存：原文件解不出缩略图打了 .failed 标记后，之后调用不应再尝试解码它。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "broken.jpg"
    real.write_bytes(b"not a real jpeg")
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="broken.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{photo_id}.failed").touch()
    api = _make_api(conn)
    monkeypatch.setattr("webview.windows", [_FakeWindow(dialog_result=None)])

    result = api.analyze_all()

    assert result["analyzed"] == 0
    assert not (cache_dir / f"{photo_id}.jpg").exists()


def test_delete_photos_continues_when_a_file_is_already_gone(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path="/nonexistent/gone.jpg", folder="/nonexistent", filename="gone.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True); (cache_dir / f"{pid}.jpg").write_bytes(b"x")
    api = _make_api(conn)
    photo_id = api.list_photos()[0]["id"]

    def fake_trash(p):
        raise OSError("file not found")

    monkeypatch.setattr("shiguang.api.send2trash", fake_trash)

    result = api.delete_photos([photo_id])

    assert result["deleted"] == 1
    assert api.list_photos() == []


import shiguang.exif_read as exif_read


def test_list_photos_fills_real_params_and_day_time(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    pid = db.list_photos(conn)[0]["id"]
    cache_dir.mkdir(parents=True, exist_ok=True); (cache_dir / f"{pid}.jpg").write_bytes(b"x")
    db.update_metadata(conn, pid, {
        "capture_time": "2024-06-14 09:12:03", "iso": 100, "shutter": "1/400s",
        "aperture": "f/2.8", "focal": "85mm", "cam": "Canon EOS R5", "size": "45.2MB",
    })
    api = _make_api(conn)

    p = api.list_photos()[0]

    assert p["day"] == "2024年6月14日"
    assert p["time"] == "09:12:03"
    assert p["iso"] == 100
    assert p["cam"] == "Canon EOS R5"
    assert p["shutter"] == "1/400s"
    assert p["aperture"] == "f/2.8"
    assert p["focal"] == "85mm"
    assert p["size"] == "45.2MB"


def test_list_photos_day_time_none_when_no_capture_time(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True); (cache_dir / f"{pid}.jpg").write_bytes(b"x")
    api = _make_api(conn)

    p = api.list_photos()[0]
    assert p["day"] is None
    assert p["time"] is None


def test_backfill_metadata_updates_photos_with_existing_files(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "real.jpg"
    _write_jpeg(real)
    gone = "/nonexistent/gone.nef"
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="real.jpg")
    db.insert_photo(conn, path=gone, folder="/nonexistent", filename="gone.nef")
    api = _make_api(conn)

    monkeypatch.setattr(exif_read, "read_metadata",
                        lambda p: {"capture_time": "2024-06-14 09:12:03", "cam": "TestCam",
                                   "iso": None, "shutter": None, "aperture": None, "focal": None, "size": None})

    result = api.backfill_metadata()

    assert result["updated"] == 1
    assert result["error"] is None
    rows = {r["filename"]: r for r in db.list_photos(conn)}
    assert rows["real.jpg"]["capture_time"] == "2024-06-14 09:12:03"
    assert rows["gone.nef"]["capture_time"] is None


import shiguang.raw_thumb as raw_thumb


def test_get_preview_generates_and_returns_url(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    preview_dir = tmp_path / "preview_cache"
    monkeypatch.setattr(api_module, "PREVIEW_CACHE_DIR", preview_dir)
    real = tmp_path / "real.jpg"
    Image.new("RGB", (4000, 3000), (10, 20, 30)).save(real)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="real.jpg")
    api = _make_api(conn)
    pid = db.list_photos(conn)[0]["id"]

    result = api.get_preview(pid)

    assert result["url"] == f"{THUMB_BASE_URL}preview_cache/{pid}.jpg"
    assert result["error"] is None
    cache_file = preview_dir / f"{pid}.jpg"
    assert cache_file.exists()
    w, h = Image.open(cache_file).size
    assert max(w, h) <= 2560
    assert max(w, h) > 512


def test_get_preview_reuses_existing_cache(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    preview_dir = tmp_path / "preview_cache"
    preview_dir.mkdir()
    monkeypatch.setattr(api_module, "PREVIEW_CACHE_DIR", preview_dir)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/whatever/real.jpg", folder="/whatever", filename="real.jpg")
    api = _make_api(conn)
    pid = db.list_photos(conn)[0]["id"]
    (preview_dir / f"{pid}.jpg").write_bytes(b"cached-preview")

    result = api.get_preview(pid)

    assert result["url"] == f"{THUMB_BASE_URL}preview_cache/{pid}.jpg"
    assert (preview_dir / f"{pid}.jpg").read_bytes() == b"cached-preview"


def test_get_original_generates_full_res_and_returns_url(tmp_path, monkeypatch):
    """全屏放大看原图：get_original 生成接近原分辨率的大图缓存并返回URL。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    orig_dir = tmp_path / "orig_cache"
    monkeypatch.setattr(api_module, "ORIG_CACHE_DIR", orig_dir)
    real = tmp_path / "big.jpg"
    Image.new("RGB", (5000, 3000), (10, 20, 30)).save(real)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="big.jpg")
    api = _make_api(conn)

    result = api.get_original(pid)

    assert result["error"] is None
    assert result["url"] == f"{THUMB_BASE_URL}orig_cache/{pid}.jpg"
    w, h = Image.open(orig_dir / f"{pid}.jpg").size
    assert max(w, h) > 2560          # 比2560预览更大(真原图级)


def test_get_original_returns_none_when_source_missing(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(api_module, "ORIG_CACHE_DIR", tmp_path / "orig_cache")
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path="/gone/x.nef", folder="/gone", filename="x.nef")
    api = _make_api(conn)

    result = api.get_original(pid)

    assert result["url"] is None
    assert result["error"] is None


def test_get_preview_returns_none_when_original_missing(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    preview_dir = tmp_path / "preview_cache"
    monkeypatch.setattr(api_module, "PREVIEW_CACHE_DIR", preview_dir)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/nonexistent/gone.nef", folder="/n", filename="gone.nef")
    api = _make_api(conn)
    pid = db.list_photos(conn)[0]["id"]

    result = api.get_preview(pid)

    assert result["url"] is None
    assert result["error"] is None


def test_get_analysis_returns_histograms_and_clipping(tmp_path, monkeypatch):
    """原文件不在，但512缩略图缓存文件在——分析应该照样能靠缓存文件跑出来。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(api_module, "PREVIEW_CACHE_DIR", tmp_path / "preview_cache")
    monkeypatch.setattr(api_module, "EXPO_CACHE_DIR", tmp_path / "expo_cache")
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path="/gone/x.jpg", folder="/gone", filename="x.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{photo_id}.jpg").write_bytes(_jpeg_bytes(color=(128, 128, 128), size=(100, 100)))
    api = _make_api(conn)

    res = api.get_analysis(photo_id)

    assert res["error"] is None
    assert len(res["histograms"]["main"]) == 64
    assert "over_pct" in res and "under_pct" in res
    assert res["overlay_url"] == f"{THUMB_BASE_URL}expo_cache/{photo_id}.jpg"
    assert (tmp_path / "expo_cache" / f"{photo_id}.jpg").exists()


def test_get_analysis_handles_no_image(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(api_module, "PREVIEW_CACHE_DIR", tmp_path / "preview_cache")
    monkeypatch.setattr(api_module, "EXPO_CACHE_DIR", tmp_path / "expo_cache")
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/gone/x.nef", folder="/gone", filename="x.nef")
    api = _make_api(conn)
    pid = db.list_photos(conn)[0]["id"]

    res = api.get_analysis(pid)

    assert res["error"] is None
    assert res["histograms"] is None
    assert res["overlay_url"] is None


def test_open_external_calls_startfile_for_existing_file(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "real.jpg"
    real.write_bytes(b"x")
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="real.jpg")
    api = _make_api(conn)
    pid = db.list_photos(conn)[0]["id"]

    opened = []
    monkeypatch.setattr("os.startfile", lambda p: opened.append(p), raising=False)

    res = api.open_external(pid)

    assert res["opened"] is True
    assert res["error"] is None
    assert opened == [str(real)]


def test_open_external_returns_false_when_file_missing(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/gone/x.nef", folder="/gone", filename="x.nef")
    api = _make_api(conn)
    pid = db.list_photos(conn)[0]["id"]

    res = api.open_external(pid)

    assert res["opened"] is False
    assert res["error"] is None


def test_analyze_all_classifies_and_persists_tier(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "a.jpg"
    _write_jpeg(real)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="a.jpg")
    api = _make_api(conn)
    monkeypatch.setattr("webview.windows", [_FakeWindow(dialog_result=None)])

    result = api.analyze_all()

    assert result["error"] is None
    assert result["analyzed"] == 1
    assert api.list_photos()[0]["tier"] in ("bad", "fix", "good")


def test_analyze_all_uses_existing_cache_file_when_source_missing(tmp_path, monkeypatch):
    """核心场景：原文件不可访问(卡拔了)，但缩略图缓存文件还在——应该照样能分析，
    数据库不存图像字节，这条路径证明"缓存独立于原图"的设计确实可用。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path="/gone/x.jpg", folder="/gone", filename="x.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{photo_id}.jpg").write_bytes(_jpeg_bytes())
    api = _make_api(conn)
    monkeypatch.setattr("webview.windows", [_FakeWindow(dialog_result=None)])

    result = api.analyze_all()

    assert result["analyzed"] == 1
    assert api.list_photos()[0]["tier"] in ("bad", "fix", "good")


def test_analyze_all_preserves_manual_tier_but_still_backfills_phash(tmp_path, monkeypatch):
    """analyze 会处理"缺phash"的照片(补phash出堆叠+用新模型重评)，但**保留用户手动改过的档**。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real_a = tmp_path / "a.jpg"
    real_b = tmp_path / "b.jpg"
    _write_jpeg(real_a)
    _write_jpeg(real_b)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real_a), folder=str(tmp_path), filename="a.jpg")
    db.insert_photo(conn, path=str(real_b), folder=str(tmp_path), filename="b.jpg")
    api = _make_api(conn)
    monkeypatch.setattr("webview.windows", [_FakeWindow(dialog_result=None)])
    b_id = [p for p in api.list_photos() if p["filename"] == "b.jpg"][0]["id"]
    api.set_tier(b_id, "good")            # 用户手动改判 b 为 good(分析前, auto_tier 为空)

    result = api.analyze_all()

    assert result["analyzed"] == 2        # 两张都处理了(a 新评; b 补phash但保留档)
    assert [p for p in api.list_photos() if p["id"] == b_id][0]["tier"] == "good"  # 手动档保留
    assert db.needs_analysis_count(conn) == 0   # 都补上 phash 了，无待处理


def test_analyze_all_pushes_progress(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    _write_jpeg(tmp_path / "a.jpg")
    _write_jpeg(tmp_path / "b.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(tmp_path / "a.jpg"), folder=str(tmp_path), filename="a.jpg")
    db.insert_photo(conn, path=str(tmp_path / "b.jpg"), folder=str(tmp_path), filename="b.jpg")
    api = _make_api(conn)
    fake_window = _FakeWindow(dialog_result=None)
    monkeypatch.setattr("webview.windows", [fake_window])

    api.analyze_all()

    assert any("onAnalyzeProgress(1, 2)" in c for c in fake_window.evaluate_js_calls)
    assert any("onAnalyzeProgress(2, 2)" in c for c in fake_window.evaluate_js_calls)


def test_analyze_all_skips_photo_when_source_unavailable(tmp_path, monkeypatch):
    """原文件不可访问 且 没有缓存文件 —— 跳过，留在未分析状态，不误标、不崩溃。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/gone/a.nef", folder="/gone", filename="a.nef")
    api = _make_api(conn)
    monkeypatch.setattr("webview.windows", [_FakeWindow(dialog_result=None)])

    result = api.analyze_all()

    assert result["error"] is None
    assert result["analyzed"] == 0
    # 该照片无源→不可显示→list_photos 不列出它；直接查库确认它没被误标(仍未分析)
    assert db.list_photos(conn)[0]["tier"] is None


# ── Phase 2E 存储卡自动检测 ────────────────────────────────────────

def test_scan_card_folders_returns_folders_with_counts(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    dcim = tmp_path / "DCIM" / "100NZ502"
    dcim.mkdir(parents=True)
    _write_jpeg(dcim / "a.jpg")
    _write_jpeg(dcim / "b.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    info = api.scan_card_folders(str(tmp_path))

    assert info["error"] is None
    assert info["total_count"] == 2
    assert len(info["folders"]) == 1
    assert info["folders"][0]["count"] == 2


def test_detect_cards_now_only_returns_cards_with_photos(tmp_path, monkeypatch):
    """空盘(没照片)不该出现在检测结果里，避免空U盘也弹窗。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    card_with = tmp_path / "cardA"
    (card_with / "DCIM").mkdir(parents=True)
    _write_jpeg(card_with / "DCIM" / "a.jpg")
    card_empty = tmp_path / "cardB"
    card_empty.mkdir()
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    # 假装这两个目录是两张可移动卡
    monkeypatch.setattr(
        "shiguang.device_watch.list_removable_drives",
        lambda: [str(card_with), str(card_empty)],
    )

    res = api.detect_cards_now()

    assert res["error"] is None
    assert len(res["cards"]) == 1                       # 只有含照片的 cardA
    assert res["cards"][0]["total_count"] == 1


def test_import_folders_imports_multiple(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    fa = tmp_path / "100NZ502"
    fb = tmp_path / "101NZ502"
    fa.mkdir(); fb.mkdir()
    _write_jpeg(fa / "a.jpg")
    _write_jpeg(fb / "b.jpg")
    _write_jpeg(fb / "c.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    result = api.import_folders([str(fa), str(fb)])

    assert result["error"] is None
    assert result["imported"] == 3
    assert len(result["photos"]) == 3
    # 导入不再在导入时写缩略图(提速)——缩略图按需生成。这里断言导入没写、按需能生成。
    pid = result["photos"][0]["id"]
    assert not (cache_dir / f"{pid}.jpg").exists()
    api.ensure_cache_file(f"thumb_cache/{pid}.jpg")
    assert (cache_dir / f"{pid}.jpg").exists()


def test_import_folders_continues_when_one_folder_fails(tmp_path, monkeypatch):
    """某个文件夹扫描失败(比如已被拔卡)不该让其他已选文件夹也白导。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    good = tmp_path / "good"
    good.mkdir()
    _write_jpeg(good / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    result = api.import_folders(["/nonexistent/gone", str(good)])

    assert result["error"] is None
    assert result["imported"] == 1
    assert len(result["photos"]) == 1


def test_import_folders_reports_global_progress(tmp_path, monkeypatch):
    """导入进度是跨所有文件夹的全局 done/total（供小导入窗显示 X/共Y张）。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    fa = tmp_path / "A"; fb = tmp_path / "B"
    fa.mkdir(); fb.mkdir()
    _write_jpeg(fa / "1.jpg"); _write_jpeg(fa / "2.jpg")
    _write_jpeg(fb / "3.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    calls = []

    api.import_folders([str(fa), str(fb)], progress_callback=lambda d, t: calls.append((d, t)))

    assert calls[-1] == (3, 3)                 # 最终 3/3
    assert all(t == 3 for _, t in calls)       # total 始终是全局总数
    assert [d for d, _ in calls] == [1, 2, 3]  # 全局递增，不是每个文件夹从1重来


def test_backfill_card_flags_marks_removable_folders(tmp_path, monkeypatch):
    """老数据(is_card=0)里,盘符当前可移动的文件夹被回填成卡来源→进侧边栏;本地的不动。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    # 模拟加列前的老数据：is_card 都是 0。卡文件夹用真实目录(list_folders 要 isdir)；
    # 本地用另一盘的假路径(不会被回填、也进不了 db.list_folders)。
    card = tmp_path / "DCIM"; card.mkdir()
    db.insert_photo(conn, path=str(card / "1.jpg"), folder=str(card), filename="1.jpg", is_card=0)
    db.insert_photo(conn, path="D:/local/x.jpg", folder="D:/local", filename="x.jpg", is_card=0)
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [drive])

    result = api.backfill_card_flags()

    assert result["error"] is None
    folders = {f["folder"] for f in api.list_folders()}
    assert folders == {str(card)}          # 可移动盘上的进侧边栏；D:/local(本地假路径)不进


def test_backfill_card_flags_noop_without_removable(tmp_path, monkeypatch):
    """没有可移动盘时(卡没插)不乱标 is_card。用一个确定不存在的路径，这样本地文件夹也因
    isdir=False 不显示，从而 list_folders 为空——单验"backfill 没把它误标成卡"。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    gone = str(tmp_path / "gone_dcim")   # 不 mkdir → isdir False
    db.insert_photo(conn, path=gone + "/1.jpg", folder=gone, filename="1.jpg", is_card=0)
    api = _make_api(conn)
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [])

    api.backfill_card_flags()
    assert api.list_folders() == []                      # 不存在→不显示；且没被误标成卡
    assert all(r["is_card"] == 0 for r in conn.execute("SELECT is_card FROM photos"))


def test_import_from_removable_marks_is_card_vs_local(tmp_path, monkeypatch):
    """从可移动盘导入的标 is_card=1(kind=card)；本地导入的 is_card=0(kind=local)。
    两者侧边栏都显示，但本地不进SD卡记忆(kind 区分)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    card_folder = tmp_path / "DCIM"
    card_folder.mkdir()
    _write_jpeg(card_folder / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    import os as _os
    drive = _os.path.splitdrive(_os.path.abspath(str(card_folder)))[0] + _os.sep
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [drive])

    api.import_folders([str(card_folder)])

    cards = api.list_folders()
    assert len(cards) == 1 and cards[0]["kind"] == "card"      # 卡文件夹进侧边栏、标card

    # 换成"没有可移动盘"再导入本地文件夹 → is_card=0、kind=local，也显示但标本地
    other = tmp_path / "local"
    other.mkdir()
    _write_jpeg(other / "b.jpg")
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda: [])
    api.import_folders([str(other)])
    by_kind = {f["folder"]: f["kind"] for f in api.list_folders()}
    assert by_kind.get(str(other)) == "local"                  # 本地也显示，标 local
    # 卡这会儿"没插"(removable=[]) → 卡文件夹不显示，只剩本地
    assert str(card_folder) not in by_kind


def test_import_folders_handles_empty_list(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    result = api.import_folders([])

    assert result["error"] is None
    assert result["imported"] == 0


# ── 托盘挂机：窗口处理器 ────────────────────────────────────────

def test_hide_to_tray_and_quit_invoke_injected_handlers(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    calls = []
    api.set_window_handlers(
        hide=lambda: calls.append("hide"),
        show=lambda: calls.append("show"),
        quit=lambda: calls.append("quit"),
    )

    assert api.hide_to_tray()["error"] is None
    assert api.quit_app()["error"] is None
    assert calls == ["hide", "quit"]


def test_hide_to_tray_and_quit_no_handler_does_not_crash(tmp_path, monkeypatch):
    """app.py 还没注入处理器(或非GUI环境)时调用不应崩溃。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    assert api.hide_to_tray()["error"] is None
    assert api.quit_app()["error"] is None


def test_rotate_photo_accumulates_and_persists(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True); (cache_dir / f"{pid}.jpg").write_bytes(b"x")
    api = _make_api(conn)

    assert api.rotate_photo(pid, 90)["rotation"] == 90
    assert api.rotate_photo(pid, 90)["rotation"] == 180    # 累加
    assert api.rotate_photo(pid, -90)["rotation"] == 90     # 逆时针
    assert api.list_photos()[0]["rotation"] == 90           # 持久化到库


def test_forget_folder_removes_records_and_cache_but_keeps_original(tmp_path, monkeypatch):
    """文件夹删除：删库记录+清缓存，但绝不动原始照片文件(可能在SD卡上)。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "keep.jpg"
    _write_jpeg(real)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="keep.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{pid}.jpg").write_bytes(b"x")
    api = _make_api(conn)

    result = api.forget_folder(str(tmp_path))

    assert result["error"] is None
    assert result["removed"] == 1
    assert api.list_photos() == []                    # 库记录没了
    assert not (cache_dir / f"{pid}.jpg").exists()    # 缓存清了
    assert real.exists()                              # 原始照片文件仍在(没删)


def test_forget_photos_by_ids_removes_only_those(tmp_path, monkeypatch):
    """按id删：只删传入的这批，不碰同文件夹其他照片(防延迟提交误删新导入的)。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    keep_real = tmp_path / "keep.jpg"
    _write_jpeg(keep_real)
    old_id = db.insert_photo(conn, path="/card/A/old.jpg", folder="/card/A", filename="old.jpg")
    new_id = db.insert_photo(conn, path=str(keep_real), folder="/card/A", filename="new.jpg")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{old_id}.jpg").write_bytes(b"x")
    (cache_dir / f"{new_id}.jpg").write_bytes(b"y")
    api = _make_api(conn)

    # 只删 old（模拟：swipe 删文件夹时该文件夹只有 old；old 提交前又导入了 new）
    result = api.forget_photos([old_id])

    assert result["removed"] == 1
    remaining = [p["id"] for p in api.list_photos()]
    assert remaining == [new_id]                          # new 还在，没被误删
    assert not (cache_dir / f"{old_id}.jpg").exists()
    assert (cache_dir / f"{new_id}.jpg").exists()


def test_import_and_finish_imports_then_shows_main(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    folder = tmp_path / "100NZ"
    folder.mkdir()
    _write_jpeg(folder / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    calls = []
    api.set_import_window_handlers(
        show_import=lambda: calls.append("show_import"),
        hide_import=lambda: calls.append("hide_import"),
        show_main=lambda: calls.append("show_main"),
        refresh_main=lambda: calls.append("refresh_main"),
    )

    result = api.import_and_finish([str(folder)])

    assert result["error"] is None
    assert result["imported"] == 1
    # 确认导入后：关小窗 → 显主窗 → 刷新主窗
    assert calls == ["hide_import", "show_main", "refresh_main"]


def test_get_pending_card_and_cancel(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    assert api.get_pending_card() == {"folders": []}     # 默认空
    api._pending_card = {"folders": [{"path": "/x", "name": "x", "count": 3}]}
    assert api.get_pending_card()["folders"][0]["count"] == 3
    hid, shown = [], []
    api.set_import_window_handlers(hide_import=lambda: hid.append(1), show_main=lambda: shown.append(1))
    api.cancel_import()
    assert hid == [1]
    assert shown == [1]   # 取消/好的 也该弹出主窗，不留用户困在托盘手动开


def test_tray_available_defaults_false_and_reflects_setter(tmp_path, monkeypatch):
    """前端靠这个判断托盘可用否：没设过默认 False(保守，宁可弹框也别让窗口回不来)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    assert api.tray_available() is False
    api.set_tray_available(True)
    assert api.tray_available() is True
    api.set_tray_available(False)
    assert api.tray_available() is False


def test_handle_card_inserted_only_new_folders_prompt(tmp_path, monkeypatch):
    """认得的卡插入：已记忆的文件夹不再弹确认窗，只有卡上"新发现、没记忆过"的才弹。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    remembered = tmp_path / "DCIM"; remembered.mkdir()
    fresh = tmp_path / "NEWDIR"; fresh.mkdir()
    # 这张卡(序列号 CARD0001)之前导入过 DCIM
    db.insert_photo(conn, path=str(remembered / "1.jpg"), folder=str(remembered),
                    filename="1.jpg", is_card=1, card_serial="CARD0001")
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    # 卡上现在扫到 两个含照片的文件夹：老的 DCIM + 新的 NEWDIR
    monkeypatch.setattr("shiguang.device_watch.find_photo_folders", lambda d: [
        {"path": str(remembered), "name": "DCIM", "count": 3, "size_mb": 10.0},
        {"path": str(fresh), "name": "NEWDIR", "count": 2, "size_mb": 5.0},
    ])
    presented = []
    api.set_import_window_handlers(present_card=lambda info: presented.append(info),
                                   refresh_main=lambda: None)

    result = api.handle_card_inserted(drive)

    assert {f["path"] for f in result["folders"]} == {str(fresh)}   # 只弹新发现的
    assert presented and {f["path"] for f in presented[0]["folders"]} == {str(fresh)}


def test_handle_card_inserted_no_new_folders_no_popup(tmp_path, monkeypatch):
    """全是已记忆文件夹 → 不弹窗，只刷新侧边栏。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    remembered = tmp_path / "DCIM"; remembered.mkdir()
    db.insert_photo(conn, path=str(remembered / "1.jpg"), folder=str(remembered),
                    filename="1.jpg", is_card=1, card_serial="CARD0001")
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    monkeypatch.setattr("shiguang.device_watch.find_photo_folders", lambda d: [
        {"path": str(remembered), "name": "DCIM", "count": 3, "size_mb": 10.0},
    ])
    presented, refreshed = [], []
    api.set_import_window_handlers(present_card=lambda info: presented.append(info),
                                   refresh_main=lambda: refreshed.append(1))

    result = api.handle_card_inserted(drive)

    assert result["folders"] == []      # 无新文件夹
    assert presented == []              # 不弹窗
    assert refreshed == [1]             # 但刷新了侧边栏


def test_handle_card_inserted_rebinds_on_letter_change(tmp_path, monkeypatch):
    """认得的卡换了盘符：记录路径重绑到当前盘符(用当前 tmp_path 盘符校验)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    real = tmp_path / "DCIM"; real.mkdir()
    cur_drive = os.path.splitdrive(os.path.abspath(str(real)))[0]   # 如 'C:'
    # 记录停在一个"别的盘符" Z:
    db.insert_photo(conn, path=r"Z:\DCIM\1.jpg", folder=r"Z:\DCIM",
                    filename="1.jpg", is_card=1, card_serial="CARD0001")
    api = _make_api(conn)
    drive = cur_drive + os.sep
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    monkeypatch.setattr("shiguang.device_watch.find_photo_folders", lambda d: [])
    api.set_import_window_handlers(refresh_main=lambda: None)

    api.handle_card_inserted(drive)

    folders = {r["folder"] for r in db.list_photos(conn)}
    assert folders == {cur_drive + r"\DCIM"}   # 已重绑到当前盘符


def test_concurrent_rebind_and_reads_no_crash(tmp_path, monkeypatch):
    """并发冒烟(_db_lock 存在的理由)：一个后台线程反复 rebind(模拟 watcher 插卡认卡)，
    多个前台线程同时反复 list_photos/get_original/ensure_cache_file(模拟 JS/HTTP 线程)，
    共用同一 check_same_thread=False 连接，断言全程不抛异常。"""
    import threading

    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    real = tmp_path / "DCIM"; real.mkdir()
    for i in range(20):
        p = real / f"{i}.jpg"
        _write_jpeg(p)
        db.insert_photo(conn, path=str(p), folder=str(real), filename=f"{i}.jpg",
                        is_card=1, card_serial="CARD0001")
    api = _make_api(conn)
    cur_drive = os.path.splitdrive(os.path.abspath(str(real)))[0]

    errors = []
    stop = threading.Event()

    def rebinder():
        flip = [cur_drive, "Z:"]
        n = 0
        try:
            while not stop.is_set():
                # 在当前盘符与 Z: 之间反复重绑(纯 DB 写，模拟反复插卡认卡)
                api.sync_card_paths_for_drive(flip[n % 2] + os.sep)
                # 直接调 db.rebind 保证真的有写发生(sync 只在盘符变化时才写)
                with api._db_lock:
                    db.rebind_card_paths(conn, "CARD0001", flip[n % 2])
                n += 1
        except Exception as e:  # noqa: BLE001
            errors.append(("rebind", repr(e)))

    def reader():
        try:
            for _ in range(200):
                api.list_photos()
                api.get_original(1)
                api.ensure_cache_file("thumb_cache/1.jpg")
        except Exception as e:  # noqa: BLE001
            errors.append(("read", repr(e)))

    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    rb = threading.Thread(target=rebinder)
    readers = [threading.Thread(target=reader) for _ in range(3)]
    rb.start()
    for t in readers:
        t.start()
    for t in readers:
        t.join()
    stop.set()
    rb.join()

    assert errors == []


def test_list_stacks_groups_similar_and_picks_sharpest_cover(tmp_path, monkeypatch):
    cache = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    cache.mkdir(parents=True, exist_ok=True)
    conn = db.connect(tmp_path / "t.sqlite")
    id1 = db.insert_photo(conn, path="E:/a/1.jpg", folder="E:/a", filename="1.jpg",
                          metadata={"cam": "R5", "capture_time": "2024-06-01 10:00:00"})
    id2 = db.insert_photo(conn, path="E:/a/2.jpg", folder="E:/a", filename="2.jpg",
                          metadata={"cam": "R5", "capture_time": "2024-06-01 10:00:01"})
    # 画面相似(中纹理 phash, hamming=1) → 折叠成组
    db.set_analysis(conn, id1, "good", phash="00ff00ff00ff00ff", focus_score=300.0)
    db.set_analysis(conn, id2, "good", phash="00ff00ff00ff00fe", focus_score=100.0)
    for pid in (id1, id2):
        _write_jpeg(cache / f"{pid}.jpg")           # 写缓存 → 可显示
    stacks = _make_api(conn).list_stacks()
    assert len(stacks) == 1
    assert set(stacks[0]["memberIds"]) == {id1, id2}
    assert stacks[0]["cover"] == id1                # focus 300 > 100 → 最锐当封面
    assert stacks[0]["similar"] is True


def test_list_stacks_excludes_unshowable(tmp_path, monkeypatch):
    """拔卡后无缓存也无原文件的照片不进堆叠(免幽灵成员)。"""
    cache = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    cache.mkdir(parents=True, exist_ok=True)
    conn = db.connect(tmp_path / "t.sqlite")
    id1 = db.insert_photo(conn, path="E:/gone/1.jpg", folder="E:/gone", filename="1.jpg",
                          metadata={"cam": "R5", "capture_time": "2024-06-01 10:00:00"})
    id2 = db.insert_photo(conn, path="E:/gone/2.jpg", folder="E:/gone", filename="2.jpg",
                          metadata={"cam": "R5", "capture_time": "2024-06-01 10:00:01"})
    db.set_analysis(conn, id1, "good", phash="0000000000000000", focus_score=300.0)
    db.set_analysis(conn, id2, "good", phash="0000000000000001", focus_score=100.0)
    assert _make_api(conn).list_stacks() == []       # 不写缓存、原文件路径也不存在


def test_backfill_phash_fills_analyzed_photos_without_phash(tmp_path, monkeypatch):
    """已分析(tier已定)但 phash 为空的老照片，backfill_phash 应补算 phash 且不动 tier。"""
    cache = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    cache.mkdir(parents=True, exist_ok=True)
    conn = db.connect(tmp_path / "t.sqlite")
    pid = db.insert_photo(conn, path="E:/a/1.jpg", folder="E:/a", filename="1.jpg",
                          metadata={"cam": "R5", "capture_time": "2024-06-01 10:00:00"})
    db.set_manual_tier(conn, pid, "good")            # 已有用户档位, 不能被覆盖
    _write_jpeg(cache / f"{pid}.jpg")                # 有缓存 → 可算 phash
    assert db.list_missing_phash(conn)               # 补前: 缺 phash

    res = _make_api(conn).backfill_phash()

    assert res["updated"] == 1 and res["error"] is None
    assert db.list_missing_phash(conn) == []         # 补后: 都有 phash 了
    assert db.list_photos(conn)[0]["tier"] == "good" # tier 没被动


def test_needs_analysis_count_only_counts_showable(tmp_path, monkeypatch):
    """拔卡后库里不可访问的记录不该计入待分析数(否则计数虚高、按钮亮着点了也没用)。"""
    cache = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    cache.mkdir(parents=True, exist_ok=True)
    conn = db.connect(tmp_path / "t.sqlite")
    show = db.insert_photo(conn, path="E:/gone/1.jpg", folder="E:/gone", filename="1.jpg")
    db.insert_photo(conn, path="E:/gone/2.jpg", folder="E:/gone", filename="2.jpg")  # 不可显示
    _write_jpeg(cache / f"{show}.jpg")                 # 只给第一张写缓存 → 只有它可显示
    api = _make_api(conn)

    assert api.needs_analysis_count()["count"] == 1    # 只数可显示的那张


def test_handle_card_inserted_known_card_notifies_when_main_hidden(tmp_path, monkeypatch):
    """真机反馈的bug：托盘挂机时拔卡重插同一张已导入过的卡(全是已记忆文件夹)，主窗又是
    隐藏的(缩托盘/最小化)——之前直接不弹窗也不给任何反馈，用户会以为没检测到。
    现在:主窗隐藏时即使没有新文件夹，也弹一下小窗告知"已识别"(mode=known)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    remembered = tmp_path / "DCIM"; remembered.mkdir()
    db.insert_photo(conn, path=str(remembered / "1.jpg"), folder=str(remembered),
                    filename="1.jpg", is_card=1, card_serial="CARD0001")
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    monkeypatch.setattr("shiguang.device_watch.find_photo_folders", lambda d: [
        {"path": str(remembered), "name": "DCIM", "count": 3, "size_mb": 10.0},
    ])
    presented = []
    api.set_window_handlers(is_hidden=lambda: True)   # 模拟主窗当前缩在托盘
    api.set_import_window_handlers(present_card=lambda info: presented.append(info),
                                   refresh_main=lambda: None)

    result = api.handle_card_inserted(drive)

    assert result["folders"] == []                    # 无新文件夹(和之前一样)
    # 先立刻弹"已识别·正在检查新照片"，增量同步完再更新成最终结果(两次都是 known 小窗)
    assert len(presented) == 2
    assert presented[0]["mode"] == "known" and presented[0]["syncing"] is True
    assert presented[-1]["mode"] == "known" and presented[-1]["syncing"] is False
    assert presented[-1]["known_count"] == 1            # 这张卡记忆过1个文件夹


def test_handle_card_inserted_known_card_no_popup_when_main_visible(tmp_path, monkeypatch):
    """同上场景，但主窗当前可见——侧边栏刷新用户看得见，不需要额外弹窗(不打扰)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    remembered = tmp_path / "DCIM"; remembered.mkdir()
    db.insert_photo(conn, path=str(remembered / "1.jpg"), folder=str(remembered),
                    filename="1.jpg", is_card=1, card_serial="CARD0001")
    api = _make_api(conn)
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    monkeypatch.setattr("shiguang.device_watch.find_photo_folders", lambda d: [
        {"path": str(remembered), "name": "DCIM", "count": 3, "size_mb": 10.0},
    ])
    presented = []
    api.set_window_handlers(is_hidden=lambda: False)  # 主窗可见
    api.set_import_window_handlers(present_card=lambda info: presented.append(info),
                                   refresh_main=lambda: None)

    api.handle_card_inserted(drive)

    assert presented == []


def test_prepare_quit_flush_and_confirm(tmp_path, monkeypatch):
    """do_quit 退出前用的事件握手：prepare_quit_flush 给一个未触发的新事件，
    confirm_flush_done 触发它——模拟前端 flushPendingDeletes 跑完后回调确认。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    event = api.prepare_quit_flush()
    assert not event.is_set()

    api.confirm_flush_done()
    assert event.is_set()


def test_prepare_quit_flush_resets_stale_event(tmp_path, monkeypatch):
    """连续两次退出流程(比如上次被取消、这次真退出)：新事件不会被上一轮的确认污染。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    first = api.prepare_quit_flush()
    api.confirm_flush_done()
    assert first.is_set()

    second = api.prepare_quit_flush()
    assert not second.is_set()   # 新一轮是全新事件，不受上一轮confirm影响


# ── 2026-10 体验大修：重插卡增量同步 / 批量改档 / 流式分析 / 后台预生成 ─────────────

def _remembered_card_with_one_photo(tmp_path, monkeypatch):
    """一张认得的卡(序列号 CARD0001)：DCIM 里 1.jpg 已导入过，现在卡上又多了 2.jpg(新拍的)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    dcim = tmp_path / "DCIM"; dcim.mkdir()
    _write_jpeg(dcim / "1.jpg")
    db.insert_photo(conn, path=str(dcim / "1.jpg"), folder=str(dcim), filename="1.jpg",
                    is_card=1, card_serial="CARD0001")
    _write_jpeg(dcim / "2.jpg")   # 插卡后新拍的，库里还没有
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    monkeypatch.setattr("shiguang.device_watch.find_photo_folders", lambda d: [
        {"path": str(dcim), "name": "DCIM", "count": 2, "size_mb": 1.0},
    ])
    return conn, dcim, drive


def test_handle_card_inserted_imports_new_files_in_remembered_folder(tmp_path, monkeypatch):
    """真机bug：用同一张卡又拍了几张、重插卡——文件夹认得就被当成"无需处理"，新拍的永远进不来。
    现在：已记忆文件夹做一次增量扫描，只导入库里还没有的新文件，并通知主窗。"""
    conn, dcim, drive = _remembered_card_with_one_photo(tmp_path, monkeypatch)
    api = _make_api(conn)
    refreshed, notes = [], []
    api.set_import_window_handlers(refresh_main=lambda: refreshed.append(1),
                                   notify_main=lambda msg: notes.append(msg))

    result = api.handle_card_inserted(drive)

    rows = {r["filename"]: r for r in conn.execute("SELECT * FROM photos")}
    assert set(rows) == {"1.jpg", "2.jpg"}
    assert rows["2.jpg"]["is_card"] == 1 and rows["2.jpg"]["card_serial"] == "CARD0001"
    assert result["synced"] == 1
    assert refreshed == [1, 1]          # 插卡先刷一次给反馈，同步出新照片后再刷一次
    assert notes and "1" in notes[0]


def test_handle_card_inserted_known_card_hidden_popup_reports_synced(tmp_path, monkeypatch):
    """主窗缩在托盘时的"已识别"小窗也要告诉用户同步进来几张新照片。"""
    conn, dcim, drive = _remembered_card_with_one_photo(tmp_path, monkeypatch)
    api = _make_api(conn)
    presented = []
    api.set_window_handlers(is_hidden=lambda: True)
    api.set_import_window_handlers(present_card=lambda info: presented.append(info),
                                   refresh_main=lambda: None)

    api.handle_card_inserted(drive)

    assert presented and presented[-1]["mode"] == "known"
    assert presented[-1]["synced_count"] == 1


def test_handle_card_inserted_no_new_files_synced_zero(tmp_path, monkeypatch):
    """卡上没有新文件：synced=0、不发"同步了N张"的通知(不打扰)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    dcim = tmp_path / "DCIM"; dcim.mkdir()
    _write_jpeg(dcim / "1.jpg")
    db.insert_photo(conn, path=str(dcim / "1.jpg"), folder=str(dcim), filename="1.jpg",
                    is_card=1, card_serial="CARD0001")
    drive = os.path.splitdrive(os.path.abspath(str(tmp_path)))[0] + os.sep
    monkeypatch.setattr("shiguang.device_watch.read_volume_serial", lambda root, **k: "CARD0001")
    monkeypatch.setattr("shiguang.device_watch.find_photo_folders", lambda d: [])
    api = _make_api(conn)
    notes = []
    api.set_import_window_handlers(refresh_main=lambda: None, notify_main=notes.append)

    result = api.handle_card_inserted(drive)

    assert result["synced"] == 0
    assert notes == []


def test_popup_cards_now_syncs_known_folders(tmp_path, monkeypatch):
    """开软件时卡已插着：同样增量同步已记忆文件夹里的新文件，返回同步张数给前端刷新。"""
    conn, dcim, drive = _remembered_card_with_one_photo(tmp_path, monkeypatch)
    monkeypatch.setattr("shiguang.device_watch.list_removable_drives", lambda *a, **k: [drive])
    api = _make_api(conn)

    result = api.popup_cards_now()

    assert result["error"] is None
    assert result["synced"] == 1
    assert {r["filename"] for r in conn.execute("SELECT filename FROM photos")} == {"1.jpg", "2.jpg"}


def test_set_tiers_updates_many_in_one_call(tmp_path, monkeypatch):
    """选中一批照片一键改档(选择栏的"标为废片/可修/精选")。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    ids = [db.insert_photo(conn, path=f"/x/{i}.jpg", folder="/x", filename=f"{i}.jpg") for i in range(3)]
    api = _make_api(conn)

    result = api.set_tiers(ids[:2], "good")

    assert result == {"updated": 2, "error": None}
    tiers = {r["id"]: r["tier"] for r in conn.execute("SELECT id, tier FROM photos")}
    assert tiers[ids[0]] == "good" and tiers[ids[1]] == "good" and tiers[ids[2]] is None


def test_analyze_all_streams_tier_batches(tmp_path, monkeypatch):
    """设计单：后台分析不阻塞浏览、结果逐步更新——分析中分批把 {id,tier} 推给前端。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    ids = []
    for i in range(3):
        p = tmp_path / f"{i}.jpg"
        _write_jpeg(p, color=(40 * i, 90, 160))
        ids.append(db.insert_photo(conn, path=str(p), folder=str(tmp_path), filename=f"{i}.jpg"))
    api = _make_api(conn)
    fake_window = _FakeWindow(dialog_result=None)
    monkeypatch.setattr("webview.windows", [fake_window])

    api.analyze_all()

    batches = [c for c in fake_window.evaluate_js_calls if "onAnalyzeBatch(" in c]
    assert batches
    pushed = "".join(batches)
    for pid in ids:
        assert f'"id": {pid}' in pushed


def test_warm_thumbnails_pregenerates_missing_caches(tmp_path, monkeypatch):
    """后台预生成：按前端给的显示顺序，把还没缓存的512缩略图提前做好(快速滑动不再一片空白)。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    ids = []
    for i in range(4):
        p = tmp_path / f"{i}.jpg"
        _write_jpeg(p, size=(900, 600))
        ids.append(db.insert_photo(conn, path=str(p), folder=str(tmp_path), filename=f"{i}.jpg"))
    gone = db.insert_photo(conn, path="/gone/x.jpg", folder="/gone", filename="x.jpg")
    api = _make_api(conn)

    api.warm_thumbnails(ids + [gone])
    assert api.wait_warm_idle(timeout=10)

    for pid in ids:
        assert (cache_dir / f"{pid}.jpg").exists()
    assert not (cache_dir / f"{gone}.jpg").exists()             # 原文件不在→跳过，不报错
    assert not list(cache_dir.glob("*.tmp"))                   # 原子写入：不留半截临时文件


def test_stop_background_halts_warmer(tmp_path, monkeypatch):
    """退出时必须先停预生成线程再清缓存，否则边清边写会留下残缺缓存。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    ids = []
    for i in range(30):
        p = tmp_path / f"{i}.jpg"
        _write_jpeg(p, size=(600, 400))
        ids.append(db.insert_photo(conn, path=str(p), folder=str(tmp_path), filename=f"{i}.jpg"))
    api = _make_api(conn)

    api.warm_thumbnails(ids)
    api.stop_background()

    assert api.wait_warm_idle(timeout=5)


def test_list_photos_includes_sortable_capture_time(tmp_path, monkeypatch):
    """前端撤销删除后要按拍摄时间放回原位：list_photos 带上可排序的原始时间 ts(无时间为 None)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "a.jpg"
    _write_jpeg(real)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="a.jpg",
                          metadata={"capture_time": "2026-10-24 09:12:03"})
    api = _make_api(conn)

    photo = [p for p in api.list_photos() if p["id"] == pid][0]

    assert photo["ts"] == "2026-10-24 09:12:03"


def test_set_pref_persists_to_prefs_file(tmp_path, monkeypatch):
    """pywebview 默认每次启动都是全新无痕配置，localStorage 关掉就丢(深色模式/记住关闭方式都会忘)。
    偏好改存后端 prefs.json：set_pref 写盘，load_prefs 读回。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    prefs_file = tmp_path / "prefs.json"
    monkeypatch.setattr(api_module, "PREFS_FILE", prefs_file)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    assert api.set_pref("shiguang-theme", "dark") == {"ok": True, "error": None}
    api.set_pref("shiguang-close-pref", "tray")

    assert api_module.load_prefs() == {"shiguang-theme": "dark", "shiguang-close-pref": "tray"}


def test_set_pref_rejects_unknown_keys_and_huge_values(tmp_path, monkeypatch):
    """只收本软件自己的偏好键(shiguang-*)、限长，防止前端误写/写爆文件。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(api_module, "PREFS_FILE", tmp_path / "prefs.json")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    assert api.set_pref("other-key", "x")["ok"] is False
    assert api.set_pref("shiguang-theme", "x" * 5000)["ok"] is False
    assert api_module.load_prefs() == {}


def test_load_prefs_tolerates_corrupt_file(tmp_path, monkeypatch):
    """prefs.json 坏了(手改/写一半断电)也不能让软件起不来：读不出就当没有偏好。"""
    bad = tmp_path / "prefs.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(api_module, "PREFS_FILE", bad)

    assert api_module.load_prefs() == {}


# ── 对抗审查发现的问题(2026-10-25)：先复现再修 ─────────────────────────────

def test_analyze_all_keeps_tier_user_changed_during_analysis(tmp_path, monkeypatch):
    """审查#1：分析进行中用户把还没轮到的照片标成精选——轮到它时不能被自动档覆盖，
    推给前端的也必须是写库后的真实档位。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    ids = []
    for i in range(2):
        p = tmp_path / f"{i}.jpg"
        _write_jpeg(p, color=(30 + 60 * i, 90, 160))
        ids.append(db.insert_photo(conn, path=str(p), folder=str(tmp_path), filename=f"{i}.jpg"))
    api = _make_api(conn)
    fake_window = _FakeWindow(dialog_result=None)
    monkeypatch.setattr("webview.windows", [fake_window])
    real_score = api_module.scoring.score_image_bytes
    calls = []

    def score_and_user_edits(image_bytes, iso=None, **kw):
        calls.append(1)
        if len(calls) == 1:
            api.set_tier(ids[1], "good")   # 分析第1张时，用户把第2张手动标成精选
        result = real_score(image_bytes, iso=iso, **kw)
        result["tier"] = "bad"
        return result

    monkeypatch.setattr(api_module.scoring, "score_image_bytes", score_and_user_edits)

    api.analyze_all()

    tiers = {r["id"]: r["tier"] for r in conn.execute("SELECT id, tier FROM photos")}
    assert tiers[ids[1]] == "good"
    pushed = "".join(c for c in fake_window.evaluate_js_calls if "onAnalyzeBatch(" in c)
    assert f'{{"id": {ids[1]}, "tier": "good"}}' in pushed


def test_thumb_failure_not_marked_when_source_vanished(tmp_path, monkeypatch):
    """审查#3：读到一半卡被拔(原文件已不在)不是"这张图坏了"，不能打永久失败标记，
    否则重插卡后这张在本次会话里再也不显示、不参与分析。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "a.jpg"
    _write_jpeg(real)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="a.jpg")
    api = _make_api(conn)

    def unplugged(path, max_size=512):
        os.remove(path)
        raise OSError("device not ready")

    monkeypatch.setattr(api_module.raw_thumb, "extract_thumbnail", unplugged)

    assert api._thumb_cache_path(pid, str(real)) is None
    assert not (cache_dir / f"{pid}.failed").exists()


def test_thumb_failure_still_marked_when_file_really_broken(tmp_path, monkeypatch):
    """原文件还在、只是解不出来(真坏了)：照旧打失败标记，免得每次都重解。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    broken = tmp_path / "b.jpg"
    broken.write_bytes(b"not a jpeg")
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(broken), folder=str(tmp_path), filename="b.jpg")
    api = _make_api(conn)

    assert api._thumb_cache_path(pid, str(broken)) is None
    assert (cache_dir / f"{pid}.failed").exists()


def test_stop_background_is_terminal(tmp_path, monkeypatch):
    """审查#5：退出流程里 stop 之后，前端防抖的 warm 调用、浏览器的按需请求都不能再写缓存
    (否则可能在清缓存之后又写回文件)。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "a.jpg"
    _write_jpeg(real)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="a.jpg")
    api = _make_api(conn)

    api.stop_background()
    assert api.warm_thumbnails([pid])["queued"] == 0
    api.ensure_cache_file(f"thumb_cache/{pid}.jpg")

    assert api.wait_warm_idle(timeout=2)
    assert not (cache_dir / f"{pid}.jpg").exists()


def test_set_pref_reports_failure_when_file_cannot_be_replaced(tmp_path, monkeypatch):
    """审查#6：偏好文件替换失败(被占用)时要如实报失败，不能返回成功却没写进去。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    prefs_file = tmp_path / "prefs.json"
    prefs_file.write_text('{"shiguang-theme": "light"}', encoding="utf-8")
    monkeypatch.setattr(api_module, "PREFS_FILE", prefs_file)
    monkeypatch.setattr(api_module.time, "sleep", lambda s: None)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    def locked(src, dst):
        raise PermissionError("in use")

    monkeypatch.setattr(api_module.os, "replace", locked)

    assert api.set_pref("shiguang-theme", "dark")["ok"] is False
    assert not list(tmp_path.glob("*.tmp"))


def test_delete_keeps_record_when_file_could_not_be_removed(tmp_path, monkeypatch):
    """写保护卡等原因删不掉文件(文件还在)：库记录不能删——否则下次插卡又被当新照片同步回来，
    而且用户以为删了其实没删。真的已经不在的文件照常清记录。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    stuck = tmp_path / "stuck.jpg"
    _write_jpeg(stuck)
    conn = db.connect(tmp_path / "test.sqlite")
    stuck_id = db.insert_photo(conn, path=str(stuck), folder=str(tmp_path), filename="stuck.jpg")
    gone_id = db.insert_photo(conn, path=str(tmp_path / "gone.jpg"), folder=str(tmp_path), filename="gone.jpg")
    api = _make_api(conn)

    def write_protected(path):
        raise OSError("write protected")

    monkeypatch.setattr(api_module, "send2trash", write_protected)

    result = api.delete_photos([stuck_id, gone_id])

    left = {r["id"] for r in conn.execute("SELECT id FROM photos")}
    assert left == {stuck_id}
    assert result["failed"] == [stuck_id]
    assert result["deleted"] == 1


def test_card_insert_gives_feedback_before_slow_sync(tmp_path, monkeypatch):
    """审查#8：卡上新拍了几百张时，增量同步要逐张读 EXIF(几秒~十几秒)。必须先刷新侧边栏/弹窗
    给反馈，再慢慢同步；同步完再刷一次并提示。"""
    conn, dcim, drive = _remembered_card_with_one_photo(tmp_path, monkeypatch)
    api = _make_api(conn)
    events = []
    real_sync = api._sync_known_folders

    def tracked_sync(d, s):
        events.append("sync")
        return real_sync(d, s)

    monkeypatch.setattr(api, "_sync_known_folders", tracked_sync)
    api.set_window_handlers(is_hidden=lambda: True)
    api.set_import_window_handlers(refresh_main=lambda: events.append("refresh"),
                                   present_card=lambda info: events.append(("present", info.get("synced_count"), info.get("syncing"))),
                                   notify_main=lambda msg: events.append("notify"))

    result = api.handle_card_inserted(drive)

    assert result["synced"] == 1
    assert events.index("refresh") < events.index("sync")              # 先刷新给反馈
    assert events[0:2] == ["refresh", ("present", 0, True)]            # 托盘里也先弹"正在检查新照片"
    assert events[-3:] == ["refresh", "notify", ("present", 1, False)]   # 同步完再刷新+提示+更新小窗


def test_small_thumb_tier_is_derived_from_512(tmp_path, monkeypatch):
    """网格小格子用的 256 档：请求时从 512 缩出(512 也没有就先从原图生成 512)。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    small_dir = tmp_path / "thumb256_cache"
    monkeypatch.setattr(api_module, "THUMB_S_CACHE_DIR", small_dir)
    real = tmp_path / "a.jpg"
    _write_jpeg(real, size=(1200, 800))
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="a.jpg")
    api = _make_api(conn)

    api.ensure_cache_file(f"thumb256_cache/{pid}.jpg")

    assert (cache_dir / f"{pid}.jpg").exists()                     # 512 顺带生成(评分/大格子用)
    small = Image.open(small_dir / f"{pid}.jpg")
    assert max(small.size) == 256


def test_small_thumb_tier_skipped_when_source_gone(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    small_dir = tmp_path / "thumb256_cache"
    monkeypatch.setattr(api_module, "THUMB_S_CACHE_DIR", small_dir)
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(tmp_path / "gone.jpg"), folder=str(tmp_path), filename="gone.jpg")
    api = _make_api(conn)

    api.ensure_cache_file(f"thumb256_cache/{pid}.jpg")   # 不抛异常

    assert not (small_dir / f"{pid}.jpg").exists()


def test_analyze_records_score_version(tmp_path, monkeypatch):
    """分析写下评分算法版本：评完不再算"待分析"；算法再升级时会重新算进来。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real = tmp_path / "a.jpg"
    _write_jpeg(real, size=(600, 400))
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real), folder=str(tmp_path), filename="a.jpg")
    api = _make_api(conn)
    assert api.needs_analysis_count()["count"] == 1

    api.analyze_all()

    assert api.needs_analysis_count()["count"] == 0
    monkeypatch.setattr(api_module.scoring, "SCORE_VERSION", api_module.scoring.SCORE_VERSION + 1)
    assert api.needs_analysis_count()["count"] == 1


def test_warm_thumbnails_small_tier_also_builds_256(tmp_path, monkeypatch):
    """网格用小档时，后台预生成顺带把 256 也做好(滚到哪儿都不用等)。"""
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    small_dir = tmp_path / "thumb256_cache"
    monkeypatch.setattr(api_module, "THUMB_S_CACHE_DIR", small_dir)
    conn = db.connect(tmp_path / "test.sqlite")
    ids = []
    for i in range(3):
        f = tmp_path / f"p{i}.jpg"
        _write_jpeg(f, size=(800, 600))
        ids.append(db.insert_photo(conn, path=str(f), folder=str(tmp_path), filename=f.name))
    api = _make_api(conn)

    api.warm_thumbnails(ids, True)
    assert api.wait_warm_idle(10)

    for pid in ids:
        assert (cache_dir / f"{pid}.jpg").exists() and (small_dir / f"{pid}.jpg").exists()


def test_warm_waits_while_foreground_generation_running(tmp_path, monkeypatch):
    """浏览器/全屏正在要图(前台生成中)时，后台预生成不动手，把读卡带宽让给眼前的。"""
    import time as _time
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(api_module, "WARM_YIELD_SEC", 0.0)
    conn = db.connect(tmp_path / "test.sqlite")
    f = tmp_path / "p.jpg"
    _write_jpeg(f, size=(600, 400))
    pid = db.insert_photo(conn, path=str(f), folder=str(tmp_path), filename="p.jpg")
    api = _make_api(conn)

    api._fg_enter()
    api.warm_thumbnails([pid])
    _time.sleep(0.4)
    assert not (cache_dir / f"{pid}.jpg").exists()     # 前台在忙：后台没抢
    api._fg_exit()
    assert api.wait_warm_idle(10)
    assert (cache_dir / f"{pid}.jpg").exists()         # 前台一闲下来就接着做



def test_analyze_uses_trusted_raw_measurement(tmp_path, monkeypatch):
    """RAW 文件、预览上有可疑迹象 → 去 RAW 里核实；RAW 实测噪点过重(信噪比 < 11 dB)判废并写明原因。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    nef = tmp_path / "DSC_0001.NEF"
    nef.write_bytes(b"fake raw")                       # 只要"原文件在"；RAW 测量本身用假结果替代
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(nef), folder=str(tmp_path), filename=nef.name)
    db.update_metadata(conn, pid, {"iso": 25600})
    api = _make_api(conn)
    api_module.THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    import numpy as np
    idx = (np.arange(512) // 32) % 2
    board = np.where((idx[:341, None] ^ idx[None, :]).astype(bool), 200, 60).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(np.stack([board] * 3, axis=-1)).save(buf, format="JPEG", quality=95)
    (api_module.THUMB_CACHE_DIR / f"{pid}.jpg").write_bytes(buf.getvalue())   # 锐利、曝光正常的预览
    seen = {}

    def fake_measure(path, jpeg_rgb=None, iso=None, want_masks=False):
        seen["iso"] = iso
        return {"trusted": True, "hl_clip_pct": 0.0, "color_clip_pct": 0.0, "shadow_pct": 0.0,
                "snr_scene_db": 8.0, "snr18_db": 14.0, "rot": 0}

    monkeypatch.setattr(api_module.raw_analysis, "measure_raw", fake_measure)
    captured = {}
    real_score = api_module.scoring.score_image_bytes

    def spy(image_bytes, **kw):
        r = real_score(image_bytes, **kw)
        captured.update(r)
        return r

    monkeypatch.setattr(api_module.scoring, "score_image_bytes", spy)
    monkeypatch.setattr("webview.windows", [_FakeWindow(dialog_result=None)])

    api.analyze_all()

    assert seen["iso"] == 25600                        # 高 ISO → 读了 RAW
    assert captured["tier"] == "bad" and "噪点" in captured["reason"]
    assert captured["metrics"]["measured_on"] == "raw"


def test_untrusted_raw_falls_back_to_preview(tmp_path, monkeypatch):
    """RAW 解出来和预览对不上(新机型/特殊压缩)：不用 RAW 结果，绝不拿解坏的数据判废。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    nef = tmp_path / "DSC_0002.NEF"
    nef.write_bytes(b"fake raw")
    conn = db.connect(tmp_path / "test.sqlite")
    pid = db.insert_photo(conn, path=str(nef), folder=str(tmp_path), filename=nef.name)
    db.update_metadata(conn, pid, {"iso": 25600})
    api = _make_api(conn)
    monkeypatch.setattr(api_module.raw_analysis, "measure_raw",
                        lambda *a, **k: {"trusted": False, "snr_scene_db": 3.0, "hl_clip_pct": 90.0,
                                         "color_clip_pct": 0.0, "shadow_pct": 0.0, "snr18_db": 3.0, "rot": 0})
    raw, is_raw = api._raw_check(str(nef), _jpeg_bytes((120, 120, 120), (512, 341)), 25600)
    assert raw is None and is_raw is True


def test_card_space_computes_avg_and_shots_left(tmp_path, monkeypatch):
    """假卡(tmp_path)+假 disk_usage：avg_mb 与 shots_left 按库内照片实际大小算。"""
    from collections import namedtuple
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    card = tmp_path / "card"
    card.mkdir()
    conn = db.connect(tmp_path / "test.sqlite")
    mb = 1024 * 1024
    for i, size in enumerate((10 * mb, 30 * mb)):
        f = card / f"DSC_{i}.NEF"
        f.write_bytes(b"\0" * size)
        db.insert_photo(conn, path=str(f), folder=str(card), filename=f.name)
    db.insert_photo(conn, path=str(card / "gone.NEF"), folder=str(card), filename="gone.NEF")
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(api_module.device_watch, "list_removable_drives", lambda: [str(card) + os.sep])
    monkeypatch.setattr(api_module.shutil, "disk_usage",
                        lambda root: Usage(64 * 1024 ** 3, 44 * 1024 ** 3, 20 * 1024 ** 3))
    res = _make_api(conn).card_space()
    assert res["error"] is None and len(res["cards"]) == 1
    c = res["cards"][0]
    assert c["avg_mb"] == 20.0
    assert c["free_gb"] == 20.0 and c["total_gb"] == 64.0
    assert c["shots_left"] == 1024


def test_card_space_no_cards(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    monkeypatch.setattr(api_module.device_watch, "list_removable_drives", lambda: [])
    assert _make_api(conn).card_space() == {"cards": [], "error": None}


def test_raw_reads_stop_for_a_model_that_never_decodes(tmp_path, monkeypatch):
    """同一机型连续 3 张 RAW 都解不对：之后这个机型不再读 RAW(省下每张几百毫秒的读卡和计算)。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)
    calls = []
    monkeypatch.setattr(api_module.raw_analysis, "measure_raw",
                        lambda *a, **k: calls.append(1) or {"trusted": False})
    dark = _jpeg_bytes((20, 20, 20), (512, 341))          # 很暗 → 值得去 RAW 核实
    for i in range(6):
        f = tmp_path / f"{i}.NEF"
        f.write_bytes(b"x")
        api._raw_check(str(f), dark, 800, cam="NIKON Z 50_2")
    assert len(calls) == 3
    f = tmp_path / "other.NEF"
    f.write_bytes(b"x")
    api._raw_check(str(f), dark, 800, cam="NIKON Z 6_3")   # 别的机型照常检查
    assert len(calls) == 4


def test_analyze_all_parallel_scores_every_photo(tmp_path, monkeypatch):
    """线程池并行分析：每张都评到、都写库，进度推到 total/total。"""
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    for i in range(12):
        f = tmp_path / f"{i}.jpg"
        _write_jpeg(f, color=(10 * i, 100, 150), size=(300, 200))
        db.insert_photo(conn, path=str(f), folder=str(tmp_path), filename=f.name)
    api = _make_api(conn)
    fake = _FakeWindow(dialog_result=None)
    monkeypatch.setattr("webview.windows", [fake])

    res = api.analyze_all()

    assert res["analyzed"] == 12
    assert conn.execute("SELECT COUNT(*) FROM photos WHERE tier IS NULL").fetchone()[0] == 0
    assert any("onAnalyzeProgress(12, 12)" in c for c in fake.evaluate_js_calls)
