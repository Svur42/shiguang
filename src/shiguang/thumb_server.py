"""本地缩略图静态服务器。

背景：pywebview 在 Windows 上用系统的 WebView2 内核渲染界面，WebView2 出于安全
限制默认禁止网页加载 file:// 本地文件地址，导致直接用文件路径当 <img src> 会全部
显示为"受损"。解决办法是在本机开一个只绑定 127.0.0.1 的迷你 HTTP 服务器，专门提供
缩略图文件，界面通过 http://127.0.0.1:端口/{id}.jpg 正常加载（浏览器天然支持、且会
按需惰性加载可见区域的图片，几千张也不会一次性全塞过来）。
"""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class _QuietHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler 默认会把每个请求打到 stderr，几千张图会刷屏，静音掉。"""

    def log_message(self, *args):
        pass


def start_thumb_server(directory):
    """在后台线程启动一个只服务 directory 目录、只绑定本机的 HTTP 服务器。
    返回 base_url（形如 http://127.0.0.1:53124/），调用方把它拼上 {id}.jpg 即可。
    端口用 0 让系统自动分配空闲端口，避免和其它程序冲突。"""
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return f"http://127.0.0.1:{port}/"
