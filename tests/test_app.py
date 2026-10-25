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


def test_write_boot_prefs_emits_js_global(tmp_path):
    """启动时把偏好写成 prefs.js(页面 <head> 同步加载)：深色模式首帧就生效，不先白后黑。"""
    target = tmp_path / "prefs.js"

    app._write_boot_prefs(target, {"shiguang-theme": "dark"})

    text = target.read_text(encoding="utf-8")
    assert text.startswith("window.__sgPrefs = ")
    assert '"shiguang-theme": "dark"' in text


def test_write_boot_prefs_never_breaks_startup(tmp_path):
    """写不进去(只读目录等)也不能让软件起不来。"""
    app._write_boot_prefs(tmp_path / "no" / "such" / "dir" / "prefs.js", {"a": "b"})   # 不抛即通过
