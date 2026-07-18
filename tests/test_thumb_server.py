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
