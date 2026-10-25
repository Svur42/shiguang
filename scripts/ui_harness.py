# -*- coding: utf-8 -*-
"""UI 测试台：在普通浏览器里跑「真实前端 + 真实后端(隔离的临时图库)」，供自动化/肉眼检查界面。

为什么需要它：pywebview 的窗口没法无头自动测试，前端改动以前只能等真机反馈。测试台把 Api 的
方法通过本地 HTTP 暴露给页面(模拟 window.pywebview.api)，缩略图仍由真实 thumb_server 按需
生成——缩略图加载、堆叠分组、评分档位都是真实后端算出来的。WebView2 与 Chromium 同内核，
在浏览器里看到的渲染/动画行为与软件里基本一致。

隔离：USERPROFILE 指向临时目录，绝不读写用户真实的 ~/.shiguang；可移动盘探测被屏蔽，
绝不扫描用户插着的真实存储卡。

用法：
  .venv/Scripts/python.exe scripts/ui_harness.py                 # 默认 240 张、端口 8765
  .venv/Scripts/python.exe scripts/ui_harness.py --slow-ms 120   # 模拟慢速读卡(每张缩略图生成多等120ms)
  .venv/Scripts/python.exe scripts/ui_harness.py --fresh         # 重新生成样片与图库
打开 http://127.0.0.1:8765/ 即可；POST /__cold 清空缩略图缓存(模拟刚启动)。
"""
import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = Path(tempfile.gettempdir()) / "shiguang_ui_harness"

SHIM = """<script>
// 测试台：用 HTTP 模拟 pywebview 的 js_api 桥(真实后端方法)
window.pywebview = { api: new Proxy({}, { get(_, name) {
  if (name === 'then') return undefined;
  return (...args) => fetch('/api/' + String(name), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args),
  }).then(r => r.json());
} }) };
</script>"""


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", type=int, default=240)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--slow-ms", type=int, default=0)
    ap.add_argument("--slow-gil", action="store_true",
                    help="慢速读卡期间占住 Python GIL(模拟 rawpy 读文件不释放 GIL 的最坏情况)")
    ap.add_argument("--days", type=int, default=4,
                    help="样片分布的拍摄天数(默认 4；设 60 左右测时间刻度尺的拥挤/按月降级)")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--name", default="default", help="图库名：不同名字互不干扰(如 big 用来测大图库)")
    return ap.parse_args()


def make_photos(dst, n, seed=7, ndays=4):
    """生成带 EXIF 的合成样片：成组的"相似连拍"(同一场景小幅抖动)穿插单张，
    分布在几天里；部分模糊(评成废片)、部分有细纹理(评成精选)。"""
    from PIL import Image, ImageDraw, ImageFilter

    dst.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    if ndays <= 4:
        days = ["2026:10:18", "2026:10:19", "2026:10:21", "2026:10:24"][:max(1, ndays)]
    else:   # 往前随机间隔 1~3 天排出 ndays 个不同日期，覆盖"日期密集"的真实图库
        import datetime
        d, ds = datetime.date(2026, 10, 24), []
        for _ in range(ndays):
            ds.append(d.strftime("%Y:%m:%d"))
            d -= datetime.timedelta(days=rnd.randint(1, 3))
        days = ds[::-1]
    W, H = 2400, 1600
    i = 0
    clock = {d: 7 * 3600 for d in days}
    while i < n:
        day = days[min(len(days) - 1, i * len(days) // n)]
        group = rnd.choice([1, 1, 1, 2, 3, 4, 6])
        bg = tuple(rnd.randint(30, 220) for _ in range(3))
        fg = tuple(rnd.randint(0, 255) for _ in range(3))
        cx, cy = rnd.randint(500, 1900), rnd.randint(400, 1200)
        base = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(base)
        for _ in range(14):
            x, y = rnd.randint(0, W), rnd.randint(0, H)
            r = rnd.randint(40, 260)
            d.ellipse((x - r, y - r, x + r, y + r),
                      fill=tuple(max(0, min(255, c + rnd.randint(-60, 60))) for c in bg))
        base = base.filter(ImageFilter.GaussianBlur(18))
        d = ImageDraw.Draw(base)
        d.ellipse((cx - 220, cy - 140, cx + 220, cy + 140), fill=fg)
        d.polygon([(cx + 200, cy - 20), (cx + 330, cy - 60), (cx + 210, cy + 30)], fill=fg)
        for k in range(0, 440, 6):   # 羽毛细纹理：让清晰的样片评分偏高
            d.line((cx - 220 + k, cy - 120, cx - 200 + k, cy + 120),
                   fill=tuple((c + 70) % 256 for c in fg), width=2)
        for _ in range(group):
            if i >= n:
                break
            img = base.transform((W, H), Image.AFFINE,
                                 (1, 0, rnd.randint(-12, 12), 0, 1, rnd.randint(-8, 8)))
            roll = rnd.random()
            if roll < 0.22:
                img = img.filter(ImageFilter.GaussianBlur(rnd.choice([4, 7, 10])))
            elif roll < 0.32:
                img = img.point(lambda v: min(255, int(v * 1.9)))
            clock[day] += rnd.choice([1, 1, 2, 40, 300, 900])
            t = clock[day]
            stamp = f"{day} {t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"
            exif = Image.Exif()
            exif[0x0110] = rnd.choice(["Z 50II", "Z 50II", "EOS R7"])
            exif[0x0132] = stamp
            sub = exif.get_ifd(0x8769)
            sub[0x9003] = stamp
            sub[0x8827] = rnd.choice([100, 200, 400, 800, 1600, 3200, 6400])
            name = f"DSC_{1000 + i:04d}.JPG"
            img.save(dst / name, quality=86, exif=exif)
            i += 1


def main():
    global HARNESS
    args = parse_args()
    if args.name != "default":
        HARNESS = HARNESS.with_name(f"{HARNESS.name}_{args.name}")
    if args.fresh and HARNESS.exists():
        shutil.rmtree(HARNESS, ignore_errors=True)
    home = HARNESS / "home"
    home.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(home)
    os.environ["HOME"] = str(home)
    sys.path.insert(0, str(ROOT / "src"))

    from shiguang import api as api_module
    from shiguang import db, device_watch
    from shiguang.thumb_server import start_thumb_server

    device_watch.list_removable_drives = lambda *a, **k: []   # 绝不碰用户真实插着的卡
    # 测试台删的是合成样片：直接删文件，不往用户的回收站里塞测试垃圾
    api_module.send2trash = lambda p: os.remove(p)

    photo_dir = HARNESS / "card" / "DCIM" / "100TEST"
    if not photo_dir.exists() or not any(photo_dir.iterdir()):
        print(f"生成 {args.photos} 张样片 → {photo_dir}", flush=True)
        make_photos(photo_dir, args.photos, ndays=args.days)

    sg_home = api_module.SHIGUANG_HOME
    for d in (api_module.THUMB_CACHE_DIR, api_module.THUMB_S_CACHE_DIR, api_module.PREVIEW_CACHE_DIR,
              api_module.EXPO_CACHE_DIR, api_module.ORIG_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    conn = db.connect(sg_home / "library.sqlite")
    holder = {"api": None}
    slow = args.slow_ms / 1000.0

    if slow:
        # 模拟读卡慢：每次从原图生成缩略图/预览都多等一会儿(按需请求和后台预生成都要付这个代价)
        real_extract = api_module.raw_thumb.extract_thumbnail

        def slow_extract(path, max_size=512):
            if args.slow_gil:
                end = time.perf_counter() + slow
                while time.perf_counter() < end:
                    pass
            else:
                time.sleep(slow)
            return real_extract(path, max_size=max_size)

        api_module.raw_thumb.extract_thumbnail = slow_extract

    def generator(rel):
        holder["api"].ensure_cache_file(rel)

    base_url = start_thumb_server(sg_home, generator=generator)
    api = api_module.Api(conn, base_url)
    holder["api"] = api
    if not db.list_photos(conn):
        print("导入并分析样片…", flush=True)
        api.import_folders([str(photo_dir)])
        api.analyze_all()

    def clear_caches():
        # 先让后台预生成停手，免得删到一半的临时文件让它写坏、给照片打上"无法预览"标记
        api._warm_stop.set()
        api.wait_warm_idle(10)
        time.sleep(0.5)   # 等在途的按需生成写完
        for d in (api_module.THUMB_CACHE_DIR, api_module.THUMB_S_CACHE_DIR, api_module.PREVIEW_CACHE_DIR,
                  api_module.EXPO_CACHE_DIR, api_module.ORIG_CACHE_DIR):
            for f in d.glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] in ("/", "/index.html", "/import_window.html"):
                # ?v=baseline 时给对照组(改版前的前端，需先放到 frontend/app_baseline.html)
                page = "app_baseline.html" if "v=baseline" in self.path else "app.html"
                if self.path.startswith("/import_window.html"):
                    page = "import_window.html"
                html = (ROOT / "frontend" / page).read_text(encoding="utf-8")
                html = html.replace("<head>", "<head>\n" + SHIM, 1)
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path.split("?")[0] == "/prefs.js":
                # 与 app.py 启动时写出的 prefs.js 同款：页面 <head> 同步拿到偏好
                body = ("window.__sgPrefs = " + json.dumps(api_module.load_prefs(), ensure_ascii=False) + ";\n")
                self._send(200, body.encode("utf-8"), "application/javascript; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"[]"
            if self.path == "/__cold":
                clear_caches()
                api._warm_stop.clear()
                self._send(200, b'{"ok":true}', "application/json")
                return
            if not self.path.startswith("/api/"):
                self._send(404, b"{}", "application/json")
                return
            name = self.path[len("/api/"):]
            fn = getattr(api, name, None)
            if name.startswith("_") or not callable(fn):
                self._send(404, b'{"error":"no such api"}', "application/json")
                return
            try:
                result = fn(*json.loads(raw or b"[]"))
            except Exception as e:  # 测试台：把异常当返回值给页面，便于排查
                result = {"error": repr(e)}
            body = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Bridge)
    print(f"UI 测试台已启动：http://127.0.0.1:{args.port}/  (图片服务 {base_url}，慢速 {args.slow_ms}ms)",
          flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
