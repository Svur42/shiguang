from PIL import Image

import shiguang.db as db
import shiguang.scanner as scanner
import shiguang.exif_read as exif_read


def test_scan_folder_imports_supported_photos_only(tmp_path):
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    Image.new("RGB", (100, 100)).save(tmp_path / "b.png")
    (tmp_path / "notes.txt").write_text("ignore me")

    conn = db.connect(tmp_path / "test.sqlite")
    imported = scanner.scan_folder(conn, tmp_path)

    assert imported == 2
    rows = db.list_photos(conn)
    assert {r["filename"] for r in rows} == {"a.jpg", "b.png"}
    assert all(r["thumbnail"] is not None for r in rows)


def test_scan_folder_skips_unreadable_file_without_crashing(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not actually a jpeg")

    conn = db.connect(tmp_path / "test.sqlite")
    imported = scanner.scan_folder(conn, tmp_path)

    assert imported == 1
    rows = db.list_photos(conn)
    assert rows[0]["filename"] == "broken.jpg"
    assert rows[0]["thumbnail"] is None


def test_scan_folder_reports_progress_for_each_file(tmp_path):
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    Image.new("RGB", (100, 100)).save(tmp_path / "b.jpg")
    Image.new("RGB", (100, 100)).save(tmp_path / "c.jpg")

    conn = db.connect(tmp_path / "test.sqlite")
    calls = []
    scanner.scan_folder(conn, tmp_path, progress_callback=lambda done, total: calls.append((done, total)))

    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_scan_folder_stores_metadata(tmp_path, monkeypatch):
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")

    fake = {"capture_time": "2024-06-14 09:12:03", "iso": 100, "shutter": "1/400s",
            "aperture": "f/2.8", "focal": "85mm", "cam": "Canon EOS R5", "size": "45.2MB"}
    monkeypatch.setattr(exif_read, "read_metadata", lambda p: dict(fake))

    scanner.scan_folder(conn, tmp_path)

    row = db.list_photos(conn)[0]
    assert row["capture_time"] == "2024-06-14 09:12:03"
    assert row["cam"] == "Canon EOS R5"
    assert row["iso"] == 100
