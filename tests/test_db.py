import shiguang.db as db


def test_insert_and_list_photo(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(
        conn,
        path="/fake/DSC_0001.jpg",
        folder="/fake",
        filename="DSC_0001.jpg",
        thumbnail=b"fake-bytes",
    )
    rows = db.list_photos(conn)
    assert len(rows) == 1
    assert rows[0]["filename"] == "DSC_0001.jpg"
    assert rows[0]["thumbnail"] == b"fake-bytes"
    assert rows[0]["tier"] is None
    assert rows[0]["auto_tier"] is None


def test_insert_photo_ignores_duplicate_path(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/DSC_0001.jpg", folder="/fake", filename="DSC_0001.jpg", thumbnail=b"a")
    db.insert_photo(conn, path="/fake/DSC_0001.jpg", folder="/fake", filename="DSC_0001.jpg", thumbnail=b"b")
    rows = db.list_photos(conn)
    assert len(rows) == 1
    assert rows[0]["thumbnail"] == b"a"


def test_set_manual_tier(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"x")
    photo_id = db.list_photos(conn)[0]["id"]

    db.set_manual_tier(conn, photo_id, "fix")

    rows = db.list_photos(conn)
    assert rows[0]["tier"] == "fix"


def test_list_photos_orders_most_recently_imported_first(tmp_path):
    """最近导入的照片排在最前面（按导入顺序倒序），这样用户导入新文件夹后
    新照片立刻出现在列表顶部，不会被按文件名打散埋进已有照片里。
    故意让文件名的字母顺序和导入顺序相反，确认排序依据的是导入顺序而不是文件名。"""
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/z_first.jpg", folder="/fake", filename="z_first.jpg", thumbnail=b"1")
    db.insert_photo(conn, path="/fake/m_second.jpg", folder="/fake", filename="m_second.jpg", thumbnail=b"2")
    db.insert_photo(conn, path="/fake/a_third.jpg", folder="/fake", filename="a_third.jpg", thumbnail=b"3")

    rows = db.list_photos(conn)

    assert [r["filename"] for r in rows] == ["a_third.jpg", "m_second.jpg", "z_first.jpg"]


def test_delete_photos_removes_rows(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"a")
    db.insert_photo(conn, path="/fake/b.jpg", folder="/fake", filename="b.jpg", thumbnail=b"b")
    db.insert_photo(conn, path="/fake/c.jpg", folder="/fake", filename="c.jpg", thumbnail=b"c")
    # 注意 list_photos 是 ORDER BY id DESC，返回顺序是 [c, b, a]（id 3,2,1）
    ids = [r["id"] for r in db.list_photos(conn)]  # [3, 2, 1]

    db.delete_photos(conn, ids[:2])  # 删 id 3 和 2，即 c 和 b

    remaining = db.list_photos(conn)
    assert len(remaining) == 1
    assert remaining[0]["filename"] == "a.jpg"  # 只剩最早插入的 a


def test_get_paths_for_ids_returns_file_paths(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/fake/a.jpg", folder="/fake", filename="a.jpg", thumbnail=b"a")
    photo_id = db.list_photos(conn)[0]["id"]

    paths = db.get_paths_for_ids(conn, [photo_id])

    assert paths == ["/fake/a.jpg"]


def test_list_folders_returns_folder_with_counts(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/card/A/1.jpg", folder="/card/A", filename="1.jpg", thumbnail=b"1")
    db.insert_photo(conn, path="/card/A/2.jpg", folder="/card/A", filename="2.jpg", thumbnail=b"2")
    db.insert_photo(conn, path="/card/B/3.jpg", folder="/card/B", filename="3.jpg", thumbnail=b"3")

    folders = db.list_folders(conn)

    by_path = {f["folder"]: f["count"] for f in folders}
    assert by_path == {"/card/A": 2, "/card/B": 1}


def test_new_columns_exist_and_default_null(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg", thumbnail=b"a")
    row = db.list_photos(conn)[0]
    for col in ("capture_time", "iso", "shutter", "aperture", "focal", "cam", "size"):
        assert col in row.keys()
        assert row[col] is None


def test_update_metadata(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg", thumbnail=b"a")
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


def test_migration_adds_columns_to_old_db(tmp_path):
    import sqlite3
    dbfile = tmp_path / "old.sqlite"
    old = sqlite3.connect(dbfile)
    old.execute("""CREATE TABLE photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE NOT NULL,
        folder TEXT NOT NULL, filename TEXT NOT NULL, thumbnail BLOB,
        tier TEXT, auto_tier TEXT)""")
    old.execute("INSERT INTO photos (path, folder, filename) VALUES ('/f/old.jpg','/f','old.jpg')")
    old.commit()
    old.close()

    conn = db.connect(dbfile)

    row = db.list_photos(conn)[0]
    assert row["filename"] == "old.jpg"
    assert row["capture_time"] is None
    assert "iso" in row.keys()


def test_list_photos_orders_by_capture_time_then_id(tmp_path):
    conn = db.connect(tmp_path / "test.sqlite")
    db.insert_photo(conn, path="/f/a.jpg", folder="/f", filename="a.jpg", thumbnail=b"a")
    db.insert_photo(conn, path="/f/b.jpg", folder="/f", filename="b.jpg", thumbnail=b"b")
    db.insert_photo(conn, path="/f/c.jpg", folder="/f", filename="c.jpg", thumbnail=b"c")
    ids = {r["filename"]: r["id"] for r in db.list_photos(conn)}
    db.update_metadata(conn, ids["b.jpg"], {"capture_time": "2024-06-14 08:00:00"})
    db.update_metadata(conn, ids["c.jpg"], {"capture_time": "2024-06-14 20:00:00"})

    order = [r["filename"] for r in db.list_photos(conn)]
    assert order == ["c.jpg", "b.jpg", "a.jpg"]
