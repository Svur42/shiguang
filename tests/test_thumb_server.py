import urllib.request

from shiguang.thumb_server import start_thumb_server


def test_thumb_server_serves_files_over_http(tmp_path):
    (tmp_path / "42.jpg").write_bytes(b"\xff\xd8\xff-pretend-jpeg-content")

    base_url = start_thumb_server(tmp_path)

    assert base_url.startswith("http://127.0.0.1:")
    with urllib.request.urlopen(f"{base_url}42.jpg", timeout=5) as resp:
        assert resp.status == 200
        assert resp.read() == b"\xff\xd8\xff-pretend-jpeg-content"


def test_thumb_server_returns_404_for_missing_file(tmp_path):
    base_url = start_thumb_server(tmp_path)

    try:
        urllib.request.urlopen(f"{base_url}does-not-exist.jpg", timeout=5)
        raised = False
    except urllib.error.HTTPError as e:
        raised = e.code == 404

    assert raised


def test_thumb_server_activate_endpoint_calls_callback(tmp_path):
    """单实例激活：GET /__activate__ 触发 on_activate(让已有实例把窗口拉前台)。"""
    fired = []
    base_url = start_thumb_server(tmp_path, on_activate=lambda: fired.append(1))

    with urllib.request.urlopen(f"{base_url}__activate__", timeout=5) as resp:
        assert resp.status == 200
    assert fired == [1]


def test_thumb_server_generates_missing_file_on_demand(tmp_path):
    """请求缺失文件时先调 generator 现场生成，再返回——缩略图懒加载的关键。"""
    calls = []

    def generator(relpath):
        calls.append(relpath)
        (tmp_path / relpath).write_bytes(b"\xff\xd8\xff-generated")

    (tmp_path / "thumb_cache").mkdir()
    base_url = start_thumb_server(tmp_path, generator=generator)

    with urllib.request.urlopen(f"{base_url}thumb_cache/7.jpg", timeout=5) as resp:
        assert resp.status == 200
        assert resp.read() == b"\xff\xd8\xff-generated"
    assert calls == ["thumb_cache/7.jpg"]
