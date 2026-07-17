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
