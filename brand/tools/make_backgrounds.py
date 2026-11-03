#!/usr/bin/env python3
"""Фоны-сетки 4K для всех цветов палитры из brand/tokens.json -> brand/backgrounds/grid_<цвет>.png
Плашку (название сериала / источник) рисуем позже, когда будут файлы шрифта Gilroy."""
import json, os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tk = json.load(open(os.path.join(ROOT, "tokens.json"), encoding="utf-8"))
W, H = tk["canvas"]["long"]["w"], tk["canvas"]["long"]["h"]
g = tk["background"]["grid"]


def rgb(hx):
    hx = hx.lstrip("#"); return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))


for name in [tk["background"]["base"]] + tk["background"]["accent"]:
    base = rgb(tk["color"][name]["hex"])
    dark = sum(base) / 3 < 128
    ln = g["line_on_dark"] if dark else g["line_on_light"]
    lc, a = rgb(ln["color"]), ln["opacity"]
    col = tuple(round(b * (1 - a) + c * a) for b, c in zip(base, lc))
    im = Image.new("RGB", (W, H), base); d = ImageDraw.Draw(im)
    x = g["origin_x"] % g["step"]
    while x < W:
        d.rectangle([x, 0, x + g["line_width"] - 1, H], fill=col); x += g["step"]
    y = g["origin_y"] % g["step"]
    while y < H:
        d.rectangle([0, y, W, y + g["line_width"] - 1], fill=col); y += g["step"]
    p = os.path.join(ROOT, "backgrounds", f"grid_{name}.png")
    im.save(p, optimize=True); print("->", p)
