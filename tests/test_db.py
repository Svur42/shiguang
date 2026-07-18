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
