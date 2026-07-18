from pathlib import Path

from PIL import Image

import shiguang.api as api_module
import shiguang.db as db
from shiguang.api import Api


def _use_isolated_thumb_cache(monkeypatch, tmp_path):
    """避免测试往真实的 ~/.shiguang/thumb_cache 写文件、也避免不同测试之间
    因为照片id重复（每个测试都是从id=1开始）而互相污染缓存内容。"""
    cache_dir = tmp_path / "thumb_cache"
    monkeypatch.setattr(api_module, "THUMB_CACHE_DIR", cache_dir)
    return cache_dir


def test_list_photos_returns_file_uri_thumbnails(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"\xff\xd8\xff-fake-jpeg-bytes")
    api = Api(conn)

    photos = api.list_photos()

    assert len(photos) == 1
    assert photos[0]["filename"] == "a.jpg"
    assert photos[0]["thumbnail"].startswith("file:")
    # 缓存文件真的写到磁盘上了，且内容和数据库里的缩略图字节一致
    cache_file = cache_dir / f"{photos[0]['id']}.jpg"
    assert cache_file.exists()
    assert cache_file.read_bytes() == b"\xff\xd8\xff-fake-jpeg-bytes"


def test_list_photos_does_not_rewrite_existing_cache_file(tmp_path, monkeypatch):
    cache_dir = _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"original-bytes")
    api = Api(conn)

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
    api = Api(conn)

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
    api = Api(conn)

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
    api = Api(conn)

    fake_window = _FakeWindow(dialog_result=[str(tmp_path)])
    monkeypatch.setattr("webview.windows", [fake_window])

    api.choose_folder_and_scan()

    assert len(fake_window.evaluate_js_calls) == 2
    assert "onImportProgress(1, 2)" in fake_window.evaluate_js_calls[0]
    assert "onImportProgress(2, 2)" in fake_window.evaluate_js_calls[1]


def test_choose_folder_and_scan_handles_cancelled_dialog(tmp_path, monkeypatch):
    _use_isolated_thumb_cache(monkeypatch, tmp_path)
    conn = db.connect(tmp_path / "test.sqlite")
    api = Api(conn)

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
    api = Api(conn)

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
    api = Api(conn)

    fake_window = _FakeWindow(dialog_result=RuntimeError("模拟对话框炸了"))
    monkeypatch.setattr("webview.windows", [fake_window])

    result = api.choose_folder_and_scan()

    assert result["error"] is not None
    assert "RuntimeError" in result["error"]
