# -*- coding: utf-8 -*-
"""生成软件图标 assets/shiguang.ico，取代任务栏/窗口/托盘的默认图标。

刻意画成与前端标题栏那个相机 SVG 同款轮廓（机身圆角矩形 + 镜头圆 + 顶部取景器
凸起），这样系统托盘/任务栏图标和窗口标题栏左上角的图标一眼看上去是同一个相机，
不再是"两个不同图标"。跑一次即可。
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "shiguang.ico"
OUT.parent.mkdir(parents=True, exist_ok=True)

S = 256                          # 高分辨率画布再缩放，边缘更平滑
F = S / 24.0                     # 标题栏 SVG 用的是 24 单位坐标系，这里等比放大
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

ACCENT = (0, 113, 227, 255)      # #0071e3 苹果蓝，和UI主题一致
WHITE = (255, 255, 255, 255)


def p(x, y):
    return (x * F, y * F)


# 圆角方形底（app图标常见形态、任务栏小尺寸也清晰）
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=ACCENT)

# 顶部取景器凸起：对应标题栏 path M8 6 L9.5 4 L14.5 4 L16 6（梯形），白色
d.polygon([p(8, 6.2), p(9.5, 4), p(14.5, 4), p(16, 6.2)], fill=WHITE)

# 相机机身：对应标题栏 rect x3 y6 w18 h14 rx2，白色圆角矩形
d.rounded_rectangle([p(3, 6), p(21, 20)], radius=int(2 * F), fill=WHITE)

# 镜头：对应标题栏 circle cx12 cy13 r4，挖成蓝色(与底色一致)读作镜头孔
lx, ly, lr = 12 * F, 13 * F, 4 * F
d.ellipse([lx - lr, ly - lr, lx + lr, ly + lr], fill=ACCENT)
# 镜头高光小白点，增加"镜头感"
hr = 1.1 * F
hx, hy = lx - 1.3 * F, ly - 1.3 * F
d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=WHITE)

# 存成多尺寸 ico（任务栏/标题栏/资源管理器/托盘各取所需）
img.save(OUT, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"[成功] 已生成图标 {OUT} ({OUT.stat().st_size} 字节)")
