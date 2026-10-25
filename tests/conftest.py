import pytest

import shiguang.api as api_module
import shiguang.app as app_module

_CACHE_DIRS = {
    "THUMB_CACHE_DIR": "thumb_cache",
    "THUMB_S_CACHE_DIR": "thumb256_cache",
    "PREVIEW_CACHE_DIR": "preview_cache",
    "EXPO_CACHE_DIR": "expo_cache",
    "ORIG_CACHE_DIR": "orig_cache",
}


@pytest.fixture(autouse=True)
def _never_touch_real_user_dirs(tmp_path, monkeypatch):
    """兜底：任何测试都不许读写用户真实的 ~/.shiguang(缓存/偏好)。单个测试里再 setattr 会覆盖这里。
    以前只有部分测试各自隔离，漏掉的会把 1.jpg 之类写进真实缓存——真实软件里 id=1 的照片就会
    显示成测试图。"""
    home = tmp_path / "_sg_home"
    for name, sub in _CACHE_DIRS.items():
        monkeypatch.setattr(api_module, name, home / sub)
        if hasattr(app_module, name):
            monkeypatch.setattr(app_module, name, home / sub)
    monkeypatch.setattr(api_module, "PREFS_FILE", home / "prefs.json")
