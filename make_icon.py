# -*- coding: utf-8 -*-
"""生成「国内期货行情面板」应用图标。

设计
----
深色圆角方砖（贴合面板本身的 dark 主题）+ 红绿蜡烛图 + 淡网格线。
涨红跌绿是国内期货的配色习惯，图标里沿用同一套色，和面板内 K 线一致。

为什么不用一张大图缩下去
------------------------
16×16 的图标只剩 14 个像素的可用面积，把 256 的细节直接缩下来会糊成一团。
所以这里**每个尺寸单独绘制**，并且分两档细节：
  · ≤ 32px：3 根蜡烛、不画网格、加粗线宽（小尺寸可读性优先）
  · ≥ 40px：5 根蜡烛 + 网格线（信息量优先）
每个尺寸内部再以 8 倍超采样绘制后 LANCZOS 缩放，边缘平滑无锯齿。

为什么自己写 ICO 容器
----------------------
不同尺寸用不同格式最稳：
  · 小尺寸（≤64）用 32bpp BMP/DIB + AND 掩码 —— 老程序（含部分安装器）只认这种
  · 大尺寸（128/256）用内嵌 PNG —— Vista 起支持，体积从 256KB 压到几 KB
Pillow 的 ICO 写出是全 PNG 或全 BMP，不能混，所以自己拼容器。

用法
----
    C:/Python314/python.exe make_icon.py

产出
----
    assets/icon.ico         多尺寸图标（16/20/24/32/40/48/64/128/256）
    assets/icon-16.png …   各尺寸单独 PNG（便于检查）
    assets/icon-64.png     站点顶栏 logo
    assets/icon-256.png    文档/预览用
    assets/icon-512.png    高清预览
    assets/icon-sheet.png  放大对照表（检查小尺寸可读性，不参与分发）
"""
import io
import os
import struct

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")

# 每个尺寸渲染时的超采样倍数（8 倍足够平滑，256*8=2048 也很快）
SS = 8

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
BMP_MAX = 64          # ≤ 此尺寸用 BMP(DIB)，以上用 PNG

# ---------------- 配色（与面板 dark 主题一致） ----------------
BG_TOP = (0x1B, 0x2A, 0x44)
BG_BOT = (0x0A, 0x11, 0x1F)
BORDER = (0x35, 0x48, 0x62)
GRID = (0x2A, 0x3D, 0x57)
UP = (0xF0, 0x44, 0x38)        # 涨 · 红
DOWN = (0x12, 0xB7, 0x6A)      # 跌 · 绿

# 蜡烛定义：(开, 收, 最低, 最高)，0=图表区顶部、1=底部；收<开 → 红涨
CANDLES_BIG = [
    (0.56, 0.70, 0.78, 0.50),   # 绿
    (0.68, 0.44, 0.74, 0.38),   # 红
    (0.46, 0.56, 0.62, 0.40),   # 绿
    (0.54, 0.30, 0.60, 0.24),   # 红
    (0.34, 0.18, 0.40, 0.12),   # 红
]
CANDLES_SMALL = [
    (0.60, 0.74, 0.82, 0.52),
    (0.72, 0.42, 0.78, 0.34),
    (0.46, 0.18, 0.52, 0.10),
]


def _lerp(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def _vertical_gradient(size, top, bottom):
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        px[0, y] = _lerp(top, bottom, y / max(size - 1, 1))
    return grad.resize((size, size), Image.NEAREST).convert("RGBA")


def render(size):
    """在 size×size 上绘制图标（内部先 8 倍超采样，再缩回）。"""
    S = size * SS
    detail = size > 32
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # ---- 圆角方砖：渐变底 + 描边 ----
    m = 0.045 * S
    rad = 0.235 * S
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, S - m, S - m], radius=rad, fill=255)
    img.paste(_vertical_gradient(S, BG_TOP, BG_BOT), (0, 0), mask)
    d.rounded_rectangle([m, m, S - m, S - m], radius=rad,
                        outline=BORDER, width=max(1, round(0.011 * S)))

    # ---- 图表区 ----
    x0, x1 = 0.175 * S, 0.825 * S
    y0, y1 = 0.235 * S, 0.775 * S
    h = y1 - y0

    def ty(v):
        """0(顶)~1(底) → 画布 y"""
        return y0 + v * h

    # ---- 网格（小尺寸不画，否则糊） ----
    if detail:
        gw = max(1, round(0.0085 * S))
        for v in (0.14, 0.40, 0.66, 0.92):
            yy = ty(v)
            d.line([(x0, yy), (x1, yy)], fill=GRID, width=gw)

    # ---- 蜡烛 ----
    spec = CANDLES_BIG if detail else CANDLES_SMALL
    n = len(spec)
    slot = (x1 - x0) / n
    body_w = slot * (0.46 if detail else 0.56)
    wick_w = max(1, round((0.020 if detail else 0.030) * S))

    for i, (o, c, lo, hi) in enumerate(spec):
        cx = x0 + slot * (i + 0.5)
        color = UP if c < o else DOWN
        # 影线
        d.line([(cx, ty(hi)), (cx, ty(lo))], fill=color, width=wick_w)
        # 实体
        top, bot = ty(min(o, c)), ty(max(o, c))
        if bot - top < max(1, round(0.012 * S)):          # 保证十字星也有实体
            bot = top + max(1, round(0.012 * S))
        d.rectangle([cx - body_w / 2, top, cx + body_w / 2, bot], fill=color)

    return img.resize((size, size), Image.LANCZOS)


# --------------------------- ICO 容器 ---------------------------
def _dib_entry(im):
    """32bpp BMP(DIB) 数据块：BITMAPINFOHEADER + 自下而上 BGRA + AND 掩码。"""
    w, h = im.size
    px = im.load()
    xor = bytearray()
    for y in range(h - 1, -1, -1):                        # DIB 行序自下而上
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        xor += row
    # AND 掩码：每行按 4 字节对齐，1=透明
    stride = ((w + 31) // 32) * 4
    and_mask = bytearray()
    for y in range(h - 1, -1, -1):
        bits = bytearray(stride)
        for x in range(w):
            if px[x, y][3] < 128:
                bits[x >> 3] |= 0x80 >> (x & 7)
        and_mask += bits
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + bytes(xor) + bytes(and_mask)


def _png_entry(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_ico(path, images):
    """images: [(size, PIL.Image)]，尺寸可混合 BMP / PNG 两种存储。"""
    entries = []
    for size, im in images:
        blob = _dib_entry(im) if size <= BMP_MAX else _png_entry(im)
        entries.append((size, blob))

    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))       # ICONDIR
    offset = 6 + 16 * len(entries)
    for size, blob in entries:
        out += struct.pack("<BBBBHHII",
                           size if size < 256 else 0,
                           size if size < 256 else 0,
                           0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for _, blob in entries:
        out += blob

    with open(path, "wb") as f:
        f.write(bytes(out))
    return len(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    images = [(s, render(s)) for s in SIZES]

    for size, im in images:
        im.save(os.path.join(OUT, "icon-%d.png" % size), "PNG")

    icopath = os.path.join(OUT, "icon.ico")
    total = write_ico(icopath, images)
    print("写出 %s  (%d 字节)" % (icopath, total))
    for size, blob in ((s, _dib_entry(i) if s <= BMP_MAX else _png_entry(i)) for s, i in images):
        print("   %3d×%-3d  %-4s  %6d 字节" % (size, size,
                                              "BMP" if size <= BMP_MAX else "PNG", len(blob)))

    # 高清预览（256 放大到 512，留作文档用）
    render(256).resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon-512.png"), "PNG")

    # 放大对照表：把小尺寸按整数倍放大，肉眼检查可读性
    zoom = {16: 8, 20: 8, 24: 6, 32: 5, 40: 4, 48: 4, 64: 3, 128: 2, 256: 1}
    pad = 16
    tiles = [im.resize((s * zoom[s], s * zoom[s]), Image.NEAREST) for s, im in images]
    W = sum(t.width for t in tiles) + pad * (len(tiles) + 1)
    H = max(t.height for t in tiles) + pad * 2
    sheet = Image.new("RGB", (W, H), (0x2B, 0x2F, 0x36))
    x = pad
    for t in tiles:
        sheet.paste(t, (x, (H - t.height) // 2), t)
        x += t.width + pad
    sheet.save(os.path.join(OUT, "icon-sheet.png"), "PNG")
    print("对照表: %s" % os.path.join(OUT, "icon-sheet.png"))


if __name__ == "__main__":
    main()
