from PIL import Image

import shiguang.db as db
import shiguang.scanner as scanner
import shiguang.exif_read as exif_read


def test_scan_folder_does_not_decode_thumbnails_at_import(tmp_path):
    """导入只建记录+读EXIF，**不再逐张解码缩略图**(那是几千张几分钟的元凶)；
    缩略图改为浏览时按需生成。所以导入后缓存目录里没有缩略图文件。"""
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    Image.new("RGB", (100, 100)).save(tmp_path / "b.png")
    (tmp_path / "notes.txt").write_text("ignore me")
    cache_dir = tmp_path / "cache"

    conn = db.connect(tmp_path / "test.sqlite")
    imported = scanner.scan_folder(conn, tmp_path, thumb_cache_dir=cache_dir)

    assert imported == 2
    rows = db.list_photos(conn)
    assert {r["filename"] for r in rows} == {"a.jpg", "b.png"}
    assert all("thumbnail" not in r.keys() for r in rows)
    for r in rows:
        assert not (cache_dir / f"{r['id']}.jpg").exists()   # 导入不写缩略图(按需生成)


def test_scan_folder_imports_unreadable_file_without_crashing(tmp_path):
    """坏文件也照常建记录(导入不解码，故不会因解不出而崩)；缩略图按需生成时才会判失败。"""
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not actually a jpeg")
    cache_dir = tmp_path / "cache"

    conn = db.connect(tmp_path / "test.sqlite")
    imported = scanner.scan_folder(conn, tmp_path, thumb_cache_dir=cache_dir)

    assert imported == 1
    rows = db.list_photos(conn)
    assert rows[0]["filename"] == "broken.jpg"
    photo_id = rows[0]["id"]
    assert not (cache_dir / f"{photo_id}.jpg").exists()      # 导入不解码,不写缓存


def test_scan_folder_works_without_cache_dir(tmp_path):
    """thumb_cache_dir 不传时只导入数据，不写任何缩略图文件——不崩溃。"""
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")

    imported = scanner.scan_folder(conn, tmp_path)

    assert imported == 1
    assert db.list_photos(conn)[0]["filename"] == "a.jpg"


def test_scan_folder_reimport_skips_existing_and_counts_only_new(tmp_path):
    """重新导入同一文件夹：已在库的跳过，只统计并处理真正新增的照片。"""
    Image.new("RGB", (100, 100)).save(tmp_path / "a.jpg")
    conn = db.connect(tmp_path / "test.sqlite")

    first = scanner.scan_folder(conn, tmp_path)
    assert first == 1

    # 再加一张新的，重新扫同一文件夹
    Image.new("RGB", (100, 100)).save(tmp_path / "b.jpg")
    second = scanner.scan_folder(conn, tmp_path)

    assert second == 1                       # 只算新增的 b，不把已存在的 a 也算进去
    assert len(db.list_photos(conn)) == 2    # 库里共 2 张，没有重复行


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
