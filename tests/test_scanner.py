from PIL import Image

import shiguang.db as db
import shiguang.scanner as scanner


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
