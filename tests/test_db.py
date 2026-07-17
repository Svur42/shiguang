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
