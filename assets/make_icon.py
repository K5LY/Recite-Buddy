#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成"添加到主屏幕"用的汉字图标（apple-touch-icon）
================================================
用法:
    python3 make_icon.py <汉字> <主色hex> <输出png路径> [--size 180]

示例:
    python3 make_icon.py 美 #B23A2F apple-touch-icon.png
    python3 make_icon.py 展 #3A5F4F apple-touch-icon.png

产出: 180x180 PNG（圆角矩形主色底 + 白色汉字，字重 Black）。
随后把图片上传为可访问 URL，写入 config.json 的 "appicon" 字段。
"""
import argparse
import os
import re

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc',
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc',
    '/System/Library/Fonts/PingFang.ttc',
    'C:/Windows/Fonts/msyhbd.ttc',
]

# Pillow ≥ 8.2 才提供 ImageDraw.textbbox / rounded_rectangle
_MIN_PILLOW = (8, 2)


def _pillow_ok():
    import PIL
    ver = tuple(int(x) for x in PIL.__version__.split('.')[:2])
    return ver >= _MIN_PILLOW


def _parse_hex(s):
    h = s.strip().lstrip('#')
    if len(h) == 3:  # 三位简写 #3AF -> #33AAFF
        h = ''.join(c * 2 for c in h)
    if not re.fullmatch(r'[0-9A-Fa-f]{6}', h):
        raise SystemExit(f'主色不是合法 hex: {s}（支持 #RGB 或 #RRGGBB）')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit('未找到中文字体，请安装 Noto Sans CJK 或修改 FONT_CANDIDATES')


def main():
    if not _pillow_ok():
        raise SystemExit('Pillow 版本过低：make_icon.py 需要 Pillow ≥ 8.2，请升级 pip install -U Pillow')
    ap = argparse.ArgumentParser()
    ap.add_argument('char', help='图标汉字，如 美 / 展')
    ap.add_argument('color', help='主色 hex，如 #3A5F4F')
    ap.add_argument('out', help='输出 PNG 路径')
    ap.add_argument('--size', type=int, default=180)
    a = ap.parse_args()
    if len(a.char) != 1:
        raise SystemExit('图标汉字必须是单个字符')
    if a.size < 60 or a.size > 1024:
        raise SystemExit('--size 建议 60–1024（默认 180）')

    rgb = _parse_hex(a.color)
    n = a.size
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角矩形底
    r = int(n * 0.22)
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=r, fill=rgb + (255,))
    # 白色汉字（占画布约 66%）
    font_path = find_font()
    fs = int(n * 0.66)
    font = ImageFont.truetype(font_path, fs)
    # 汉字在 TrueType 字体里通常有下沉余量，用 bbox 精确居中
    bbox = d.textbbox((0, 0), a.char, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (n - w) / 2 - bbox[0]
    y = (n - h) / 2 - bbox[1]
    d.text((x, y), a.char, font=font, fill=(255, 255, 255, 255))
    img.save(a.out, 'PNG')
    print('icon saved:', a.out, f'{n}x{n}', 'bg', a.color)


if __name__ == '__main__':
    main()
