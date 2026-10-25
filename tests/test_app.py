import shiguang.app as app
import shiguang.api as api_module


def test_clear_caches_removes_cache_files_but_keeps_library(tmp_path, monkeypatch):
    """关软件清缓存：删四个图像缓存目录的文件，但绝不动 library.sqlite（记忆）。"""
    home = tmp_path / ".shiguang"
    thumb = home / "thumb_cache"
    preview = home / "preview_cache"
    expo = home / "expo_cache"
    orig = home / "orig_cache"
    for d in (thumb, preview, expo, orig):
        d.mkdir(parents=True)
        (d / "1.jpg").write_bytes(b"x")
        (d / "2.failed").write_bytes(b"")
    library = home / "library.sqlite"
    library.write_bytes(b"THE-MEMORY-DB")

    monkeypatch.setattr(app, "THUMB_CACHE_DIR", thumb)
    monkeypatch.setattr(app, "PREVIEW_CACHE_DIR", preview)
    monkeypatch.setattr(app, "EXPO_CACHE_DIR", expo)
    monkeypatch.setattr(app, "ORIG_CACHE_DIR", orig)

    app._clear_caches()

    for d in (thumb, preview, expo, orig):
        assert list(d.glob("*")) == []           # 缓存都清了
    assert library.read_bytes() == b"THE-MEMORY-DB"  # 记忆库原封不动


def test_clear_caches_survives_missing_dirs(tmp_path, monkeypatch):
    """缓存目录不存在时也不崩(比如从没导入过)。"""
    home = tmp_path / ".shiguang"
    monkeypatch.setattr(app, "THUMB_CACHE_DIR", home / "thumb_cache")
    monkeypatch.setattr(app, "PREVIEW_CACHE_DIR", home / "preview_cache")
    monkeypatch.setattr(app, "EXPO_CACHE_DIR", home / "expo_cache")
    monkeypatch.setattr(app, "ORIG_CACHE_DIR", home / "orig_cache")

    app._clear_caches()   # 不抛异常即通过
