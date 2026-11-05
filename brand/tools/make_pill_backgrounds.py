#!/usr/bin/env python3
"""Фоны с сеткой и плашкой «Теория Большого взрыва» во всех цветах палитры.
Берёт настоящий синий фон (insert_maker/assets/bg_4k.png), вычисляет слой «линии + плашка»
как прозрачность поверх синего и переносит его на остальные цвета:
на тёмных — светлые линии, на бежевом — тёмные.
-> brand/backgrounds/pill_<цвет>.png"""
import json, os
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
tk = json.load(open(os.path.join(ROOT, "tokens.json"), encoding="utf-8"))
rgb = lambda h: np.array([int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)], np.float32)

src = np.asarray(Image.open(os.path.join(REPO, "insert_maker", "assets", "bg_4k.png")).convert("RGB"), np.float32)
base = np.median(src[600:700, 600:700].reshape(-1, 3), 0)
a = np.clip(((src - base) / (255 - base)).mean(2), 0, 1)[..., None]      # белый поверх синего

for name in [tk["background"]["base"]] + tk["background"]["accent"]:
    c = rgb(tk["color"][name]["hex"])
    dark = c.mean() < 128
    ink = np.array([255, 255, 255], np.float32) if dark else np.array([0, 0, 0], np.float32)
    k = 1.0 if dark else 1.15                                             # на светлом линии чуть плотнее
    out = c * (1 - a * k) + ink * (a * k)
    p = os.path.join(ROOT, "backgrounds", f"pill_{name}.png")
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(p, optimize=True)
    print("->", p)
