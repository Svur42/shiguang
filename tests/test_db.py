import shiguang.db as db


def test_insert_and_list_photo(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    photo_id = db.insert_photo(conn, path="/fake/DSC_0001.jpg", folder="/fake", filename="DSC_0001.jpg")
    rows = db.list_photos(conn)
    assert len(rows) == 1
    assert rows[0]["filename"] == "DSC_0001.jpg"
    assert rows[0]["id"] == photo_id
    assert rows[0]["tier"] is None
    assert rows[0]["auto_tier"] is None
    # 数据库只存数据(路径/编号/标签/EXIF)，不再有任何图像字节列
    assert "thumbnail" not in rows[0].keys()


def test_insert_photo_ignores_duplicate_path(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    id1 = db.insert_photo(conn, path="/fake/DSC_0001.jpg", folder="/fake", filename="DSC_0001.jpg")
    id2 = db.insert_photo(conn, path="/fake/DSC_0001.jpg", folder="/fake", filename="DSC_0001.jpg")
    rows = db.list_photos(conn)
    assert len(rows) == 1
    # 重复路径不产生新行，且返回的是同一个既有 id（调用方靠这个 id 命名缓存文件）
    assert id1 == id2


def test_set_manual_tier(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg")
    photo_id = db.list_photos(conn)[0]["id"]

    db.set_manual_tier(conn, photo_id, "fix")

    rows = db.list_photos(conn)
    assert rows[0]["tier"] == "fix"


def test_set_auto_tier_writes_both_columns(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg")
    photo_id = db.list_photos(conn)[0]["id"]

    db.set_auto_tier(conn, photo_id, "good")

    row = db.list_photos(conn)[0]
    assert row["tier"] == "good"
    assert row["auto_tier"] == "good"


def test_list_unanalyzed_returns_path_and_iso_not_image_bytes(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", metadata={"iso": 400})
    photo_id = db.list_photos(conn)[0]["id"]
    other_id = db.insert_photo(conn, path="/fake/b.jpg", folder="/fake", filename="b.jpg")
    db.set_manual_tier(conn, other_id, "good")  # 已分档的不该出现在待分析列表里

    rows = db.list_unanalyzed(conn)

    assert len(rows) == 1
    assert rows[0]["id"] == photo_id
    assert rows[0]["path"] == "/fake/a.jpg"
    assert rows[0]["iso"] == 400
    assert "thumbnail" not in rows[0].keys()


def test_list_photos_orders_most_recently_imported_first(tmp_path):
    """最近导入的照片排在最前面（按导入顺序倒序），这样用户导入新文件夹后
    新照片立刻出现在列表顶部，不会像"按文件名排序"那样被打散、埋进已有照片里。
    故意让文件名的字母顺序和导入顺序相反，确认排序依据的是导入顺序而不是文件名。"""
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/z_first.jpg", folder="/fake", filename="z_first.jpg")
    db.insert_photo(conn, path="/fake/m_second.jpg", folder="/fake", filename="m_second.jpg")
    db.insert_photo(conn, path="/fake/a_third.jpg", folder="/fake", filename="a_third.jpg")

    rows = db.list_photos(conn)

    assert [r["filename"] for r in rows] == ["a_third.jpg", "m_second.jpg", "z_first.jpg"]


def test_delete_photos_removes_rows(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg")
    db.insert_photo(conn, path="/fake/b.jpg", folder="/fake", filename="b.jpg")
    db.insert_photo(conn, path="/fake/c.jpg", folder="/fake", filename="c.jpg")
    # 注意 list_photos 是 ORDER BY id DESC，返回顺序是 [c, b, a]（id 3,2,1）
    ids = [r["id"] for r in db.list_photos(conn)]  # [3, 2, 1]

    db.delete_photos(conn, ids[:2])  # 删 id 3 和 2，即 c 和 b

    remaining = db.list_photos(conn)
    assert len(remaining) == 1
    assert remaining[0]["filename"] == "a.jpg"  # 只剩最早插入的 a


def test_get_paths_for_ids_returns_file_paths(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg")
    photo_id = db.list_photos(conn)[0]["id"]

    paths = db.get_paths_for_ids(conn, [photo_id])

    assert paths == ["/fake/a.jpg"]


def test_list_folders_returns_only_card_folders_with_counts(tmp_path):
    """侧边栏只列SD卡(is_card=1)的文件夹；本地(is_card=0)不列。"""
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/card/A/1.jpg", folder="/card/A", filename="1.jpg", is_card=1)
    db.insert_photo(conn, path="/card/A/2.jpg", folder="/card/A", filename="2.jpg", is_card=1)
    db.insert_photo(conn, path="/card/B/3.jpg", folder="/card/B", filename="3.jpg", is_card=1)
    db.insert_photo(conn, path="/local/x.jpg", folder="/local", filename="x.jpg", is_card=0)

    folders = db.list_folders(conn)

    by_path = {f["folder"]: f["count"] for f in folders}
    assert by_path == {"/card/A": 2, "/card/B": 1}   # 本地 /local 不出现


def test_new_columns_exist_and_default_null(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    row = db.list_photos(conn)[0]
    for col in ("capture_time", "iso", "shutter", "aperture", "focal", "cam", "size"):
        assert col in row.keys()
        assert row[col] is None


def test_update_metadata(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    pid = db.list_photos(conn)[0]["id"]

    db.update_metadata(conn, pid, {
        "capture_time": "2024-06-14 09:12:03",
        "iso": 100, "shutter": "1/400s", "aperture": "f/2.8",
        "focal": "85mm", "cam": "Canon EOS R5", "size": "45.2MB",
    })

    row = db.list_photos(conn)[0]
    assert row["capture_time"] == "2024-06-14 09:12:03"
    assert row["iso"] == 100
    assert row["cam"] == "Canon EOS R5"


def test_migration_adds_columns_and_drops_thumbnail_from_old_db(tmp_path):
    """老库(改架构前)会有 thumbnail BLOB 列且可能存了真实图像字节；升级后应该：
    1) 照常补齐 EXIF 列 2) 丢弃 thumbnail 列——图像字节不再当"记忆"永久存库。"""
    import sqlite3
    dbfile = tmp_path / "old.sqlite"
    old = sqlite3.connect(dbfile)
    old.execute("""CREATE TABLE photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL,
        folder TEXT NOT NULL, filename TEXT NOT NULL, thumbnail BLOB,
        tier TEXT, auto_tier TEXT)""")
    old.execute("INSERT INTO photos (path, folder, filename, thumbnail) VALUES ('/f/old.jpg','/f','old.jpg', X'0102')")
    old.commit()
    old.close()

    conn = db.connect(dbfile)

    row = db.list_photos(conn)[0]
    assert row["filename"] == "old.jpg"
    assert row["capture_time"] is None
    assert "iso" in row.keys()
    assert "thumbnail" not in row.keys()


def test_migration_vacuums_to_reclaim_disk_space(tmp_path):
    """DROP COLUMN 只改schema不收缩文件——老库里几万字节的图像blob被删掉后，
    库文件应该真的变小(靠 VACUUM)，不然用户会觉得"删了但没生效"。"""
    import sqlite3
    dbfile = tmp_path / "old.sqlite"
    old = sqlite3.connect(dbfile)
    old.execute("""CREATE TABLE photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL,
        folder TEXT NOT NULL, filename TEXT NOT NULL, thumbnail BLOB,
        tier TEXT, auto_tier TEXT)""")
    big_blob = b"x" * 200_000
    for i in range(20):
        old.execute(
            "INSERT INTO photos (path, folder, filename, thumbnail) VALUES (?,?,?,?)",
            (f"/f/old{i}.jpg", "/f", f"old{i}.jpg", big_blob),
        )
    old.commit()
    old.close()
    size_before = dbfile.stat().st_size

    db.connect(dbfile)

    size_after = dbfile.stat().st_size
    assert size_after < size_before / 2   # 200KB x 20 张的blob应该被真正收回


def test_rotation_defaults_zero_and_set_rotation_persists(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    pid = db.list_photos(conn)[0]["id"]
    assert db.list_photos(conn)[0]["rotation"] == 0

    db.set_rotation(conn, pid, 90)
    assert db.list_photos(conn)[0]["rotation"] == 90
    db.set_rotation(conn, pid, 450)          # 归一化 450%360=90
    assert db.list_photos(conn)[0]["rotation"] == 90
    db.set_rotation(conn, pid, 360)          # 归一化到 0
    assert db.list_photos(conn)[0]["rotation"] == 0


def test_get_ids_for_folder(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/card/A/1.jpg", folder="/card/A", filename="1.jpg")
    db.insert_photo(conn, path="/card/A/2.jpg", folder="/card/A", filename="2.jpg")
    db.insert_photo(conn, path="/card/B/3.jpg", folder="/card/B", filename="3.jpg")

    ids = db.get_ids_for_folder(conn, "/card/A")
    assert len(ids) == 2


def test_migration_adds_rotation_column_to_old_db(tmp_path):
    import sqlite3
    dbfile = tmp_path / "old.sqlite"
    old = sqlite3.connect(dbfile)
    old.execute("""CREATE TABLE photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL,
        folder TEXT NOT NULL, filename TEXT NOT NULL, tier TEXT, auto_tier TEXT)""")
    old.execute("INSERT INTO photos (path, folder, filename) VALUES ('/f/o.jpg','/f','o.jpg')")
    old.commit(); old.close()

    conn = db.connect(dbfile)
    row = db.list_photos(conn)[0]
    assert "rotation" in row.keys()
    assert row["rotation"] == 0


def test_insert_photo_raises_clear_error_on_not_null_violation(tmp_path):
    """folder/filename 是 NOT NULL，若被静默 IGNORE 掉，之前会在 row["id"] 处
    炸出和真实原因无关的 TypeError；现在应该给出能一眼看懂原因的报错。"""
    import pytest
    conn = db.connect(tmp_path / "test.sqlite")
    with pytest.raises(RuntimeError):
        db.insert_photo(conn, path="/fake/a.jpg", folder=None, filename="a.jpg")


def test_list_photos_orders_by_capture_time_then_id(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    db.insert_photo(conn, path="/f/b.jpg", folder="/f", filename="b.jpg")
    db.insert_photo(conn, path="/f/c.jpg", folder="/f", filename="c.jpg")
    ids = {r["filename"]: r["id"] for r in db.list_photos(conn)}
    db.update_metadata(conn, ids["b.jpg"], {"capture_time": "2024-06-14 08:00:00"})
    db.update_metadata(conn, ids["c.jpg"], {"capture_time": "2024-06-14 20:00:00"})

    order = [r["filename"] for r in db.list_photos(conn)]
    assert order == ["c.jpg", "b.jpg", "a.jpg"]


def test_card_serial_stored_and_folders_for_serial(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.insert_photo(conn, path="E:/DCIM/1.jpg", folder="E:/DCIM", filename="1.jpg",
                    is_card=1, card_serial="AAAA1111")
    db.insert_photo(conn, path="E:/PRIV/2.jpg", folder="E:/PRIV", filename="2.jpg",
                    is_card=1, card_serial="AAAA1111")
    db.insert_photo(conn, path="E:/OTHER/3.jpg", folder="E:/OTHER", filename="3.jpg",
                    is_card=1, card_serial="BBBB2222")
    assert db.folders_for_serial(conn, "AAAA1111") == {"E:/DCIM", "E:/PRIV"}
    assert db.folders_for_serial(conn, "BBBB2222") == {"E:/OTHER"}
    assert db.folders_for_serial(conn, None) == set()
    # list_folders 带出 card_serial
    by = {f["folder"]: f["card_serial"] for f in db.list_folders(conn)}
    assert by["E:/DCIM"] == "AAAA1111"


def test_rebind_card_paths_swaps_drive_letter(tmp_path):
    """同一张卡换盘符(E:→F:)：该卡所有 path/folder 盘符被重绑到 F:。"""
    conn = db.connect(tmp_path / "t.sqlite")
    db.insert_photo(conn, path=r"E:\DCIM\1.jpg", folder=r"E:\DCIM", filename="1.jpg",
                    is_card=1, card_serial="AAAA1111")
    db.insert_photo(conn, path=r"E:\DCIM\2.jpg", folder=r"E:\DCIM", filename="2.jpg",
                    is_card=1, card_serial="AAAA1111")
    rebound, skipped = db.rebind_card_paths(conn, "AAAA1111", "F:")
    assert (rebound, skipped) == (2, 0)
    paths = {r["path"] for r in db.list_photos(conn)}
    assert paths == {r"F:\DCIM\1.jpg", r"F:\DCIM\2.jpg"}
    assert {r["folder"] for r in db.list_photos(conn)} == {r"F:\DCIM"}


def test_rebind_card_paths_skips_collision(tmp_path):
    """重绑后新路径若已被别的记录占用(UNIQUE)，那一行跳过、不崩溃。"""
    conn = db.connect(tmp_path / "t.sqlite")
    # 目标盘 F: 已有一张 F:\DCIM\1.jpg
    db.insert_photo(conn, path=r"F:\DCIM\1.jpg", folder=r"F:\DCIM", filename="1.jpg",
                    is_card=1, card_serial="ZZZZ9999")
    # E 卡的 1.jpg 重绑到 F: 会撞上上面那条
    db.insert_photo(conn, path=r"E:\DCIM\1.jpg", folder=r"E:\DCIM", filename="1.jpg",
                    is_card=1, card_serial="AAAA1111")
    rebound, skipped = db.rebind_card_paths(conn, "AAAA1111", "F:")
    assert skipped == 1                    # 撞车被 IGNORE
    assert db.path_exists(conn, r"E:\DCIM\1.jpg")   # 撞车的那条留旧路径不崩


def test_rebind_card_paths_noop_same_drive(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    db.insert_photo(conn, path=r"F:\DCIM\1.jpg", folder=r"F:\DCIM", filename="1.jpg",
                    is_card=1, card_serial="AAAA1111")
    assert db.rebind_card_paths(conn, "AAAA1111", "F:") == (0, 0)


def test_old_score_version_counts_as_needing_analysis(tmp_path):
    """评分算法升级后：用旧版评的照片算进"待分析"，用新版评过的不算；手动改过的档重评时保留。"""
    conn = db.connect(tmp_path / "test.sqlite")
    a = db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg")
    b = db.insert_photo(conn, path="/f/b.jpg", folder="/f", filename="b.jpg")
    db.set_analysis_auto(conn, a, "bad", phash="00ff", focus_score=1.0, score_ver=2)
    db.set_analysis_auto(conn, b, "bad", phash="00ff", focus_score=1.0)        # 旧代码写的：无版本
    assert {r["id"] for r in db.list_needs_analysis(conn, 2)} == {b}
    assert db.needs_analysis_count(conn, 2) == 1
    assert db.needs_analysis_count(conn, 3) == 2                               # 再升级一次：都要重评
    db.set_manual_tiers(conn, [a], "good")                                     # 用户手动改成精选
    assert db.set_analysis_auto(conn, a, "fix", phash="00ff", focus_score=1.0, score_ver=3) == "good"
    assert db.needs_analysis_count(conn, 3) == 1
