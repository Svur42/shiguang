# -*- coding: utf-8 -*-
"""生成软件图标 assets/shiguang.ico，取代任务栏/窗口的默认Python图标。
用软件主题色(苹果蓝)画一个简约相机镜头，风格贴合极简UI。跑一次即可。"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "shiguang.ico"
OUT.parent.mkdir(parents=True, exist_ok=True)

# 高分辨率画布再缩放，边缘更平滑
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

ACCENT = (0, 113, 227, 255)   # #0071e3 苹果蓝，和UI主题一致
WHITE = (255, 255, 255, 255)

# 圆角方形底（app图标常见形态）
radius = int(S * 0.22)
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=ACCENT)

# 相机镜头：白色外圈 + 蓝色内圈 + 白色高光点
cx, cy = S // 2, int(S * 0.54)
r_outer = int(S * 0.26)
d.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], fill=WHITE)
r_inner = int(S * 0.17)
d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], fill=ACCENT)
r_hi = int(S * 0.05)
hx, hy = cx - int(r_inner * 0.4), cy - int(r_inner * 0.4)
d.ellipse([hx - r_hi, hy - r_hi, hx + r_hi, hy + r_hi], fill=WHITE)

# 顶部取景器凸起（相机感）
vw, vh = int(S * 0.16), int(S * 0.06)
vx, vy = int(S * 0.24), int(S * 0.20)
d.rounded_rectangle([vx, vy, vx + vw, vy + vh], radius=vh // 2, fill=WHITE)

# 存成多尺寸 ico（任务栏/标题栏/资源管理器各取所需）
img.save(OUT, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"[成功] 已生成图标 {OUT} ({OUT.stat().st_size} 字节)")
