from PIL import Image

import shiguang.db as db
from shiguang.api import Api


def test_list_photos_returns_data_url_thumbnails(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"\xff\xd8\xff")
    api = Api(conn)

    photos = api.list_photos()

    assert len(photos) == 1
    assert photos[0]["filename"] == "a.jpg"
    assert photos[0]["thumbnail"].startswith("data:image/jpeg;base64,")


def test_list_photos_returns_none_thumbnail_when_missing(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/broken.jpg", folder="/fake", filename="broken.jpg", thumbnail=None)
    api = Api(conn)

    photos = api.list_photos()

    assert photos[0]["thumbnail"] is None


def test_choose_folder_and_scan_imports_photos(tmp_path, monkeypatch):
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")
    api = Api(conn)

    class FakeWindow:
        def create_file_dialog(self, dialog_type):
            return [str(tmp_path)]

    monkeypatch.setattr("webview.windows", [FakeWindow()])

    result = api.choose_folder_and_scan()

    assert result["imported"] == 1
    assert len(result["photos"]) == 1


def test_choose_folder_and_scan_handles_cancelled_dialog(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "test.sqlite")
    api = Api(conn)

    class FakeWindow:
        def create_file_dialog(self, dialog_type):
            return None

    monkeypatch.setattr("webview.windows", [FakeWindow()])

    result = api.choose_folder_and_scan()

    assert result["imported"] == 0
    assert result["error"] is None


def test_choose_folder_and_scan_from_background_thread_does_not_crash(tmp_path, monkeypatch):
    """回归测试：pywebview真实环境下，js_api方法是在独立于主线程的后台线程被调用的。
    之前 db.connect() 没传 check_same_thread=False 时，这个场景会抛
    sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread。
    这里在主线程建连接、在另一个线程调用，模拟真实场景。"""
    import threading

    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")  # 主线程创建
    api = Api(conn)

    class FakeWindow:
        def create_file_dialog(self, dialog_type):
            return [str(tmp_path)]

    monkeypatch.setattr("webview.windows", [FakeWindow()])

    outcome = {}

    def call_from_background_thread():
        outcome["result"] = api.choose_folder_and_scan()

    thread = threading.Thread(target=call_from_background_thread)
    thread.start()
    thread.join()

    assert outcome["result"]["error"] is None
    assert outcome["result"]["imported"] == 1


def test_choose_folder_and_scan_returns_error_field_instead_of_raising(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "test.sqlite")
    api = Api(conn)

    class FakeWindow:
        def create_file_dialog(self, dialog_type):
            raise RuntimeError("模拟对话框炸了")

    monkeypatch.setattr("webview.windows", [FakeWindow()])

    result = api.choose_folder_and_scan()

    assert result["error"] is not None
    assert "RuntimeError" in result["error"]
