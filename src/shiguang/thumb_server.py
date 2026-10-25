"""本地静态服务器（支持缩略图按需生成）。

背景：pywebview 在 Windows 上用系统的 WebView2 内核渲染界面，WebView2 出于安全
限制默认禁止网页加载 file:// 本地文件地址，导致直接用文件路径当 <img src> 会全部
显示为"受损"。解决办法是在本机开一个只绑定 127.0.0.1 的迷你 HTTP 服务器，提供
本地图片文件。

服务的是 ~/.shiguang 根目录，其下含 thumb_cache（缩略图）/ preview_cache（预览）
/ orig_cache（原图）/ expo_cache（过曝图）。界面通过 http://127.0.0.1:端口/子目录/{id}.jpg 加载。

按需生成：缩略图缓存会在"关软件时被清空"（用户决策），所以重开后缓存是空的。若在
list_photos 里同步把上千张全生成一遍会很慢、还阻塞。改成——浏览器请求某张缩略图时，
服务器发现文件不存在就调 generator 现场从原图生成再返回。配合前端懒加载(只请求可见
的那些)，重开秒开、缩略图随滚动即时补齐，不必一次性全做。
"""

import os
import threading
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class _QuietHandler(SimpleHTTPRequestHandler):
    """静音日志 + 按需生成：请求的文件不存在时，先调服务器的 generator 尝试生成。"""

    def log_message(self, *args):
        pass

    def do_GET(self):
        path_only = urllib.parse.urlparse(self.path).path
        # 单实例激活端点：另一个新进程发现已有实例在跑，会 GET 这个让本实例把窗口拉到前台
        if path_only == "/__activate__":
            cb = getattr(self.server, "on_activate", None)
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        gen = getattr(self.server, "generator", None)
        if gen is not None:
            fs_path = self.translate_path(self.path)
            if not os.path.exists(fs_path):
                try:
                    rel = path_only.lstrip("/")
                    gen(rel)   # 现场从原图生成这个缓存文件（失败则忽略，交给下面 404）
                except Exception:
                    pass
        return super().do_GET()


def start_thumb_server(directory, generator=None, on_activate=None):
    """在后台线程启动一个只服务 directory 目录、只绑定本机的 HTTP 服务器。
    generator(relpath) 可选：请求的文件缺失时调用它按需生成（relpath 形如
    "thumb_cache/123.jpg"）。on_activate() 可选：GET /__activate__ 时调用(单实例把窗口拉前台)。
    返回 base_url（形如 http://127.0.0.1:53124/）。端口用 0 让系统自动分配。"""
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.generator = generator
    server.on_activate = on_activate
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return f"http://127.0.0.1:{port}/"
