# -*- coding: utf-8 -*-
"""
站点图标生成器（纯 Python 标准库，无第三方依赖）。

设计与 app/static/favicon.svg 同源：深蓝港湾底 + 白色船锚 + 青色波浪，
在本文件里用距离函数逐像素重绘，输出多尺寸 favicon.ico；
可选生成一张大尺寸 PNG 预览便于人工检查。

用法：
  python3 tools/make_favicon.py [预览PNG路径]
产物：app/static/favicon.ico（16/32/48 三尺寸，32bpp）
"""
import math
import os
import struct
import sys
import zlib

# ---------- 设计（64x64 设计坐标，与 favicon.svg 对齐） ----------
BG_HI = (23, 80, 126)     # 渐变亮端 #17507E
BG_LO = (11, 34, 55)      # 渐变暗端 #0B2237
ANCHOR = (237, 245, 249)  # #EDF5F9
WAVE = (61, 185, 206)     # #3DB9CE
STROKE = 2.0              # 描边半宽（设计单位）


def _seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)


def _inside_bg(x, y):
    # 圆角矩形 [2,62]x[2,62] r=14
    cx = min(max(x, 16), 48)
    cy = min(max(y, 16), 48)
    return math.hypot(x - cx, y - cy) <= 14 and 2 <= x <= 62 and 2 <= y <= 62


def _is_anchor(x, y):
    if abs(math.hypot(x - 32, y - 13.5) - 4.6) <= STROKE:      # 锚环
        return True
    if _seg_dist(x, y, 32, 18.5, 32, 44) <= STROKE:            # 锚杆
        return True
    if _seg_dist(x, y, 22.5, 26.5, 41.5, 26.5) <= STROKE:      # 横杆
        return True
    if y >= 34 and abs(math.hypot(x - 32, y - 34) - 14.5) <= STROKE:  # 锚爪弧
        return True
    for seg in ((14.8, 29.8, 17.5, 35.5), (17.5, 35.5, 23.2, 34.8),
                (49.2, 29.8, 46.5, 35.5), (46.5, 35.5, 40.8, 34.8)):
        if _seg_dist(x, y, *seg) <= STROKE:                    # 爪尖
            return True
    return False


def _is_wave(x, y):
    if not (9 <= x <= 55):
        return False
    yc = 53.25 + 2.25 * math.sin(2 * math.pi * (x - 9) / 23 + 0.6)
    return abs(y - yc) <= 1.5


def _pixel(x, y):
    """设计坐标 (x, y) 处的 RGBA。"""
    if not _inside_bg(x, y):
        return (0, 0, 0, 0)
    t = (x + y) / 128.0
    r = BG_HI[0] + (BG_LO[0] - BG_HI[0]) * t
    g = BG_HI[1] + (BG_LO[1] - BG_HI[1]) * t
    b = BG_HI[2] + (BG_LO[2] - BG_HI[2]) * t
    a = 255.0
    if _is_wave(x, y):
        r, g, b = WAVE
    if _is_anchor(x, y):
        r, g, b = ANCHOR
    return (r, g, b, a)


def render(size, ss=4):
    """渲染 size x size 的 RGBA 像素（列表的行列表），ss 为超采样倍数。"""
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(ss):
                for sx in range(ss):
                    dx = (px + (sx + 0.5) / ss) * 64.0 / size
                    dy = (py + (sy + 0.5) / ss) * 64.0 / size
                    pr, pg, pb, pa = _pixel(dx, dy)
                    # 按 alpha 预乘后平均，保证透明边缘不发黑/发白
                    acc[0] += pr * pa
                    acc[1] += pg * pa
                    acc[2] += pb * pa
                    acc[3] += pa
            n = ss * ss
            a = acc[3] / n
            if a > 0:
                row.append((int(acc[0] / acc[3]), int(acc[1] / acc[3]),
                            int(acc[2] / acc[3]), int(a)))
            else:
                row.append((0, 0, 0, 0))
        rows.append(row)
    return rows


# ---------- ICO 写出（32bpp BMP 条目） ----------
def _bmp_entry(rows):
    size = len(rows)
    mask_row = ((size + 31) // 32) * 4
    img = bytearray()
    for row in reversed(rows):  # BMP 自下而上
        for (r, g, b, a) in row:
            img += bytes((b, g, r, a))
    img += b"\x00" * (mask_row * size)  # AND 掩码全 0，透明走 alpha 通道
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         len(img), 0, 0, 0, 0)
    return header + bytes(img)


def write_ico(path, sizes=(16, 32, 48)):
    entries = [_bmp_entry(render(s)) for s in sizes]
    out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for s, data in zip(sizes, entries):
        out += struct.pack("<BBBBHHII", s if s < 256 else 0, s if s < 256 else 0,
                           0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for data in entries:
        out += data
    with open(path, "wb") as f:
        f.write(bytes(out))
    return len(out)


def write_png(path, size=256):
    rows = render(size, ss=2)
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for (r, g, b, a) in row:
            raw += bytes((r, g, b, a))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw)))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(here, "..", "app", "static", "favicon.ico")
    n = write_ico(ico_path)
    print(f"favicon.ico written: {ico_path} ({n} bytes)")
    if len(sys.argv) > 1:
        write_png(sys.argv[1])
        print(f"preview png written: {sys.argv[1]}")
