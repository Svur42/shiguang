from pathlib import Path

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


def test_list_photos_returns_http_url_thumbnails(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"\xff\xd8\xff-fake-jpeg-bytes")
    api = _make_api(conn)

    photos = api.list_photos()

    assert len(photos) == 1
    assert photos[0]["filename"] == "a.jpg"
    # 返回的是本地缩略图HTTP服务器的地址，形如 http://127.0.0.1:端口/{id}.jpg
    # 不能是 file:// —— WebView2 会拦截本地文件地址导致图片显示为受损
    assert photos[0]["thumbnail"] == f"{THUMB_BASE_URL}{photos[0]['id']}.jpg"
    # 缓存文件真的写到磁盘上了，且内容和数据库里的缩略图字节一致
    cache_file = cache_dir / f"{photos[0]['id']}.jpg"
    assert cache_file.exists()
    assert cache_file.read_bytes() == b"\xff\xd8\xff-fake-jpeg-bytes"


def test_list_photos_does_not_rewrite_existing_cache_file(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"original-bytes")
    api = _make_api(conn)

    photos = api.list_photos()
    cache_file = cache_dir / f"{photos[0]['id']}.jpg"
    assert cache_file.read_bytes() == b"original-bytes"

    # 手动改一下缓存文件内容，再调用一次list_photos，验证它不会覆盖已存在的缓存
    # （这是刻意的行为：缓存写一次就够了，重复调用不应该反复写磁盘）
    cache_file.write_bytes(b"manually-modified")
    api.list_photos()
    assert cache_file.read_bytes() == b"manually-modified"


def test_list_photos_returns_none_thumbnail_when_missing(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/broken.jpg", folder="/fake", filename="broken.jpg", thumbnail=None)
    api = _make_api(conn)

    photos = api.list_photos()

    assert photos[0]["thumbnail"] is None


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
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = _make_api(conn)

    fake_window = _FakeWindow(dialog_result=[str(tmp_path)])
    monkeypatch.setattr("webview.windows", [fake_window])

    result = api.choose_folder_and_scan()

    assert result["imported"] == 1
    assert len(result["photos"]) == 1
    assert result["error"] is None


def test_choose_folder_and_scan_pushes_progress_via_evaluate_js(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    Image.new("RGB", (100, 100)).save(tmp_path / "b.jpg")
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
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
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
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/card/A/x.jpg", folder="/card/A", filename="x.jpg", thumbnail=b"\xff\xd8\xff")
    api = _make_api(conn)

    p = api.list_photos()[0]

    # 字段名必须和原型读取处一致：原型读 p.cam / p.shutter / p.aperture / p.focal
    assert p["folder"] == "/card/A"
    assert p["tier"] is None
    for key in ("day", "time", "burst", "iso", "cam", "shutter", "aperture", "focal", "size"):
        assert key in p


def test_set_tier_persists(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"a")
    api = _make_api(conn)
    photo_id = api.list_photos()[0]["id"]

    api.set_tier(photo_id, "fix")

    assert api.list_photos()[0]["tier"] == "fix"


def test_list_folders_returns_real_folders(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/card/A/1.jpg", folder="/card/A", filename="1.jpg", thumbnail=b"1")
    db.insert_photo(conn, path="/card/B/2.jpg", folder="/card/B", filename="2.jpg", thumbnail=b"2")
    api = _make_api(conn)

    folders = api.list_folders()

    assert {f["folder"] for f in folders} == {"/card/A", "/card/B"}
    by_path = {f["folder"]: f["name"] for f in folders}
    assert by_path == {"/card/A": "A", "/card/B": "B"}


def test_delete_photos_moves_files_to_trash_and_removes_rows(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    real_file = tmp_path / "real.jpg"
    real_file.write_bytes(b"content")
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path=str(real_file), folder=str(tmp_path), filename="real.jpg", thumbnail=b"t")
    api = _make_api(conn)
    photo_id = api.list_photos()[0]["id"]

    trashed = []
    monkeypatch.setattr("shiguang.api.send2trash", lambda p: trashed.append(p))

    result = api.delete_photos([photo_id])

    assert result["deleted"] == 1
    assert result["error"] is None
    assert trashed == [str(real_file)]
    assert api.list_photos() == []


def test_delete_photos_continues_when_a_file_is_already_gone(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/nonexistent/gone.jpg", folder="/nonexistent", filename="gone.jpg", thumbnail=b"t")
    api = _make_api(conn)
    photo_id = api.list_photos()[0]["id"]

    def fake_trash(p):
        raise OSError("file not found")

    monkeypatch.setattr("shiguang.api.send2trash", fake_trash)

    result = api.delete_photos([photo_id])

    assert result["deleted"] == 1
    assert api.list_photos() == []
