#!/usr/bin/env python3
"""
Несколько карточек-скриншотов друг под другом на фоне вставок: у каждой выделение абзаца, потом перевод
(картинки перевода готовит make_insert.py --dump), плюс наклейки по бокам. Когда приходит следующая карточка,
предыдущая плавно уезжает вверх, освобождая место.

    # 1) на каждый скриншот: оригинал + перевод картинками
    python3 make_insert.py work/x/a.png --sel 1:2-7:-1 --ru '§Заголовок:§ текст' --font grotesk --dump work/x/a
    # 2) сцена
    python3 make_stack.py scene.json [--preview]

scene.json:
{
 "duration": 19, "out": "work/trailer/trailer.mp4", "bg": "vignette-red", "title": "Очень странные дела",
 "source": "CFPB, 2014", "source_at": 0.6,
 "cards": [{"pre": "work/x/a", "w": 2500, "at": [1920, 1050], "t": 0.3, "hl_t": 1.6, "ru_t": 3.0,
            "moves": [{"t": 10.8, "dur": 1.0, "at": [1920, 760]}]}, ...],
 "stickers": [{"img", "at", "w", "rot", "t"}]
}
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import make_collage as mc  # noqa: E402
import make_levels as ml  # noqa: E402
import make_zoomrow as mz  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30


def sweep(shape, rects, p, feather):
    """Маска «слева направо по строкам»: p от 0 до 1."""
    h, w = shape
    xs = np.arange(w, dtype=np.float32)[None, :]
    m = np.zeros((h, w), np.float32)
    tot = sum(r[2] - r[0] for r in rects)
    dist = p * (tot + feather * len(rects)); off = 0.0
    for j, (x0, y0, x1, y1) in enumerate(rects):
        front = x0 + dist - off - feather * j
        v = np.clip((front - xs) / feather + 0.5, 0, 1) * ((xs >= x0 - 1) & (xs <= x1 + 1))
        ya, yb = max(0, int(y0)), min(h, int(y1))
        m[ya:yb] = np.maximum(m[ya:yb], v)
        off += x1 - x0
    return m


class Card:
    def __init__(self, cfg):
        self.cfg = cfg
        d = json.load(open(cfg["pre"] + "_rects.json"))
        A = Image.open(cfg["pre"] + "_orig.png").convert("RGB"); R = Image.open(cfg["pre"] + "_ru.png").convert("RGB")
        self.k = cfg["w"] / A.width                       # масштаб карточки в кадре
        self.size = (cfg["w"], round(A.height * self.k))
        self.A = np.asarray(A, np.float32); self.R = np.asarray(R, np.float32)
        self.hl = d["hl_rects"]; self.ru = d["ru_rects"]
        self.feather_h = 6 * d["K"]; self.feather_r = 14 * d["K"]
        rad = int(0.02 * self.size[0])
        self.alpha = Image.new("L", self.size, 0)
        ImageDraw.Draw(self.alpha).rounded_rectangle([0, 0, self.size[0] - 1, self.size[1] - 1], rad, fill=255)
        pad = int(0.06 * self.size[0])
        sh = Image.new("L", (self.size[0] + 2 * pad, self.size[1] + 2 * pad), 0)
        ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 0.02 * self.size[1], pad + self.size[0], pad + self.size[1] + 0.02 * self.size[1]], rad, fill=150)
        self.shadow = sh.filter(ImageFilter.GaussianBlur(0.02 * self.size[0])); self.pad = pad
        self._cache = {}

    def image(self, hp, rp):
        key = (round(hp, 2), round(rp, 2))
        if key not in self._cache:
            if len(self._cache) > 6:
                self._cache.clear()
            img = self.A
            if hp > 0:
                m = sweep(img.shape[:2], self.hl, hp, self.feather_h)[..., None]
                img = img * (1 - m * (1 - mi.HL_COLOR / 255))
            if rp > 0:
                m = sweep(img.shape[:2], self.ru, rp, self.feather_r)[..., None]
                img = img + (self.R - img) * m
            im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize(self.size, Image.LANCZOS).convert("RGBA")
            im.putalpha(self.alpha)
            self._cache[key] = im
        return self._cache[key]


def build(cfg, bg):
    cards = [Card(c) for c in cfg["cards"]]
    stickers = ml.load_stickers(cfg.get("stickers", []))
    cap = mz.caption_layer(cfg, bg) if cfg.get("source") else None

    def pos(spec, t):
        x, y = spec["at"]
        for mv in spec.get("moves", []):
            q = M.ease((t - mv["t"]) / mv.get("dur", 1.0))
            if q <= 0:
                break
            x += (mv["at"][0] - x) * q; y += (mv["at"][1] - y) * q
        return x, y

    def frame(t):
        out = bg.copy()
        if cap is not None:
            ca = M.ease_out((t - cfg.get("source_at", 0.5)) / M.CAPTION)
            if ca > 0:
                c = cap[0].copy(); c.putalpha(c.getchannel("A").point(lambda v: int(v * ca)))
                out.paste(c, (0, int(cap[1] + 20 * (1 - ca))), c)
        for cd, spec in zip(cards, cfg["cards"]):
            u = t - spec["t"]
            if u < 0:
                continue
            hp = M.ease((t - spec["hl_t"]) / M.HIGHLIGHT_INSERT)
            rp = M.ease((t - spec["ru_t"]) / M.TRANSLATE)
            im = cd.image(hp, rp)
            p = M.pop(u, M.CARD_IN, M.OVERSHOOT)
            s = 0.88 + 0.12 * p
            op = M.ease_out(u / M.CARD_FADE)
            x, y = pos(spec, t)
            y += 70 * (1 - M.ease_out(u / M.CARD_IN))               # въезжает снизу и встаёт
            w2, h2 = round(im.width * s), round(im.height * s)
            card = im.resize((w2, h2), Image.BILINEAR)
            if op < 1:
                card.putalpha(card.getchannel("A").point(lambda v: int(v * op)))
            sh = cd.shadow.resize((round(cd.shadow.width * s), round(cd.shadow.height * s)), Image.BILINEAR).point(lambda v: int(v * op))
            out.paste((0, 0, 0), (round(x - sh.width / 2), round(y - sh.height / 2)), sh)
            out.paste(card, (round(x - w2 / 2), round(y - h2 / 2)), card)
        ml.draw_stickers(out, stickers, t)
        return out

    return frame


_F = None


def _init(cfg):
    global _F
    _F = build(cfg, mc.scene_bg(cfg))


def _render(t):
    return _F(t).tobytes()


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    T = cfg["duration"]
    stem = os.path.splitext(cfg["out"])[0]
    if "--preview" in sys.argv:
        frame = build(cfg, mc.scene_bg(cfg))
        for i, t in enumerate(cfg.get("preview_at") or [1.0, 2.4, 4.5, T - 0.05]):
            p = f"{stem}_preview_{i}.png"; frame(t).resize((W // 2, H // 2), Image.LANCZOS).save(p)
            print("->", p, f"t={t:.2f}")
        return
    n = int(round(T * FPS))
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                           "-pix_fmt", "yuv420p", "-movflags", "+faststart", cfg["out"]], stdin=subprocess.PIPE)
    from multiprocessing import Pool
    with Pool(4, initializer=_init, initargs=(cfg,)) as pool:
        for buf in pool.imap(_render, [k / FPS for k in range(n)], chunksize=4):
            ff.stdin.write(buf)
    ff.stdin.close(); ff.wait()
    print(f"{n}/{n} -> {cfg['out']}")


if __name__ == "__main__":
    main()
