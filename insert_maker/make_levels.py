#!/usr/bin/env python3
"""
Шкала «уровней» 1–20 (как в игре) на фоне вставок: стикеры по бокам шлёпаются и покачиваются,
заголовок, 20 столбиков каскадом от бедных к богатым, номера, стрелка «беднее → богаче»,
выделение уровня 1 и уровня 20 с подписями. Высоты столбиков — условные (иллюстрация порядка,
не данные), поэтому на них нет чисел.

    python3 make_levels.py scene.json [--preview]

scene.json:
{
  "duration": 7.3, "out": "work/levels/levels.mp4", "bg": "vignette-red", "title": "Очень странные дела",
  "headline": "Уровень от 1 до 20",
  "low": "5% самых бедных", "high": "5% самых богатых", "left_word": "беднее", "right_word": "богаче",
  "stickers": [{"img": "work/levels/st/bikes.png", "at": [450, 720], "w": 560, "rot": -6, "t": 0.05}, ...],
  "bars_t": 1.2, "numbers_t": 2.0, "axis_t": 2.6, "low_t": 3.9, "high_t": 5.4
}
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import make_polaroids as mp  # noqa: E402
import make_collage as mc  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
CREAM = (246, 238, 222)
HL_YELLOW = (250, 227, 145)          # бренд: выделение на тёмном — светло-жёлтый (~#FAE391)

N = 20
BAR_W, GAP = 70, 22
BASE_Y = 1640
X0 = (W - (N * BAR_W + (N - 1) * GAP)) // 2


def bar_h(i):                         # условная «лестница доходов»: внизу плотно, наверху резко выше
    return 110 + 640 * (i / (N - 1)) ** 1.7


def bar_x(i):
    return X0 + i * (BAR_W + GAP)


def body_font(size):
    return ImageFont.truetype(mi.body_font_path(), size)


def st_font(size, ch="А"):
    return mp._st_font(size, mi.is_cyr(ch))


def text_sprite(text, font_fn, size, fill, sp=0.0, lining=False):
    """Строка как RGBA-спрайт (Playfair: кириллица и цифры — разные файлы, поэтому по буквам).
    lining — цифры подгоняются под высоту прописных: у Playfair они «старинные» (разной высоты),
    а PIL без libraqm не включает ровные цифры."""
    fonts = [font_fn(size, ch) for ch in text]
    cap = None
    if lining:
        f0 = font_fn(size, "Т"); bb = f0.getbbox("Т", anchor="ls"); cap = bb[3] - bb[1]
    parts = []
    for ch, f in zip(text, fonts):
        if lining and ch.isdigit():
            g = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
            ImageDraw.Draw(g).text((size // 2, size * 1.5), ch, font=f, fill=fill, anchor="ls")
            g = g.crop(g.getbbox()); g = g.resize((max(1, round(g.width * cap / g.height)), cap), Image.LANCZOS)
            parts.append(("img", g, g.width + 0.06 * size))
        else:
            parts.append(("txt", (ch, f), f.getlength(ch)))
    w = int(sum(a for _, _, a in parts) + sp * size * (len(text) - 1)) + 20
    im = Image.new("RGBA", (w, int(size * 1.5)), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    x = 10; base = size * 1.1
    for kind, obj, a in parts:
        if kind == "img":
            im.alpha_composite(obj, (round(x), round(base - obj.height)))
        else:
            d.text((x, base), obj[0], font=obj[1], fill=fill, anchor="ls")
        x += a + sp * size
    return im.crop(im.getbbox())


def fade(im, op):
    if op >= 1:
        return im
    im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * op))); return im


def load_stickers(specs):
    """Стикеры: картинка в нужной ширине и мягкая тень."""
    out = []
    for k, s in enumerate(specs):
        im = Image.open(s["img"]).convert("RGBA")
        sc = s["w"] / im.width
        im = im.resize((round(im.width * sc), round(im.height * sc)), Image.LANCZOS)
        pad = int(0.1 * im.width)
        sh = Image.new("L", (im.width + 2 * pad, im.height + 2 * pad), 0)
        sh.paste(im.getchannel("A").point(lambda v: int(v * 0.55)), (pad, pad))
        sh = sh.filter(ImageFilter.GaussianBlur(0.04 * im.width))
        out.append(dict(s, im=im, sh=sh, k=k))
    return out


def draw_stickers(out, stickers, t):
    """Шлепок с перелётом, доворот, тень «приподнят → прилип», фоновое покачивание."""
    for s in stickers:
        u = t - s["t"]
        if u < 0:
            continue
        p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
        sc = 1 + M.LEVEL_SLAP * (1 - p)
        ang = s.get("rot", 0) + (12 if s["k"] % 2 else -12) * (1 - M.ease_out(u / M.STICKER_TURN))
        ang += M.FACE_SWAY * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + s["k"])
        op = M.ease_out(u / M.APPEAR)
        lift = 1 - M.ease_out(u / M.STICKER_LAND)
        im = s["im"].resize((max(2, round(s["im"].width * sc)), max(2, round(s["im"].height * sc))), Image.BILINEAR)
        im = fade(im.rotate(ang, Image.BICUBIC, expand=True), op)
        k = sc * (1 + 0.06 * lift)
        sh = s["sh"].resize((max(2, round(s["sh"].width * k)), max(2, round(s["sh"].height * k))), Image.BILINEAR)
        sh = sh.rotate(ang, Image.BILINEAR, expand=True).point(lambda v: int(v * op))
        x, y = s["at"]
        out.paste((0, 0, 0), (round(x - sh.width / 2), round(y - sh.height / 2 + (0.02 + 0.05 * lift) * im.height)), sh)
        out.paste(im, (round(x - im.width / 2), round(y - im.height / 2)), im)


def build(cfg, bg):
    T = cfg["duration"]
    stickers = load_stickers(cfg["stickers"])
    headline = text_sprite(cfg["headline"].upper(), lambda sz, ch: st_font(sz, ch), 130, CREAM, sp=0.05, lining=True)
    low_tag = text_sprite("УРОВЕНЬ 1", lambda sz, ch: st_font(sz, ch), 112, HL_YELLOW, sp=0.04, lining=True)
    high_tag = text_sprite("УРОВЕНЬ 20", lambda sz, ch: st_font(sz, ch), 112, HL_YELLOW, sp=0.04, lining=True)
    low_txt = text_sprite(cfg["low"], lambda sz, ch: body_font(sz), 82, CREAM)
    high_txt = text_sprite(cfg["high"], lambda sz, ch: body_font(sz), 82, CREAM)
    nums = [text_sprite(str(i + 1), lambda sz, ch: body_font(sz), 58, CREAM) for i in range(N)]
    lw = text_sprite(cfg["left_word"], lambda sz, ch: body_font(sz), 66, CREAM)
    rw = text_sprite(cfg["right_word"], lambda sz, ch: body_font(sz), 66, CREAM)

    def frame(t):
        out = bg.copy()
        d = ImageDraw.Draw(out, "RGBA")
        draw_stickers(out, stickers, t)
        # --- заголовок
        u = t - cfg.get("headline_t", 0.45)
        if u > 0:
            q = M.ease_out(u / M.CARD_FADE)
            hl = fade(headline, q)
            out.paste(hl, (round(W / 2 - hl.width / 2), round(360 + 30 * (1 - q))), hl)
        # --- столбики: каскадом слева направо, растут снизу с небольшим перелётом
        lo = M.ease((t - cfg["low_t"]) / M.DIM)                     # с выделения — остальные тише
        for i in range(N):
            u = t - cfg["bars_t"] - i * M.LEVEL_STAGGER
            if u <= 0:
                continue
            g = M.pop(u, M.LEVEL_GROW, M.LEVEL_OVERSHOOT)
            h = bar_h(i) * max(0.0, g)
            x = bar_x(i)
            is_low = i == 0; is_high = i == N - 1
            hi = M.ease((t - cfg["high_t"]) / M.DIM) if is_high else 0.0
            sel = M.ease((t - cfg["low_t"]) / M.DIM) if is_low else hi
            base_a = 0.9 * (1 - 0.6 * lo * (1 - sel))
            col = tuple(int(c0 + (c1 - c0) * sel) for c0, c1 in zip(CREAM, HL_YELLOW))
            if h > 1:
                d.rounded_rectangle([x, BASE_Y - h, x + BAR_W, BASE_Y], radius=10, fill=col + (int(255 * base_a),))
        # --- номера под столбиками
        for i in range(N):
            u = t - cfg["numbers_t"] - i * M.LEVEL_STAGGER * 0.5
            if u <= 0:
                continue
            q = M.ease_out(u / M.WORD_FADE / 2)
            sel = 1.0 if (i == 0 and t > cfg["low_t"]) or (i == N - 1 and t > cfg["high_t"]) else 0.0
            n = fade(nums[i], q * (0.75 + 0.25 * sel) * (1 - 0.5 * lo * (1 - sel)))
            out.paste(n, (round(bar_x(i) + BAR_W / 2 - n.width / 2), BASE_Y + 40), n)
        # --- ось «беднее → богаче»: линия тянется слева направо, слова проявляются
        u = t - cfg["axis_t"]
        if u > 0:
            q = M.ease(u / M.LEVEL_AXIS)
            ay = BASE_Y + 170; xa = X0; xb = X0 + (bar_x(N - 1) + BAR_W - X0) * q
            d.line([xa, ay, xb, ay], fill=CREAM + (150,), width=4)
            if q > 0.9:
                d.polygon([(xb, ay), (xb - 26, ay - 14), (xb - 26, ay + 14)], fill=CREAM + (150,))
            wq = M.ease_out((u - 0.3) / M.CARD_FADE)
            if wq > 0:
                a_ = fade(lw, 0.8 * wq); b_ = fade(rw, 0.8 * wq)
                out.paste(a_, (X0, ay + 34), a_)
                out.paste(b_, (round(bar_x(N - 1) + BAR_W - b_.width), ay + 34), b_)
        # --- подписи уровней: ярлык + строка, тонкая линия к столбику
        def label(tag, txt, t0, bx, top_y, align, bar_top=None):
            u = t - t0 - 0.15
            if u <= 0:
                return
            q = M.pop(u, M.WORD_IN, M.OVERSHOOT_SMALL); op = M.ease_out(u / M.WORD_FADE)
            ly = top_y - 70
            y_end = (bar_top if bar_top is not None else top_y) - 16           # линия до самого столбика
            y_line = ly + 30 + (y_end - ly - 30) * (1 - M.ease(u / M.PIN_LINE))
            d.line([bx, y_end, bx, y_line], fill=HL_YELLOW + (int(200 * op),), width=4)
            tg = fade(tag, op); tx = fade(txt, op)
            dy = 30 * (1 - q)
            x_t = bx - 10 if align == "left" else bx + 10 - max(tg.width, tx.width)
            out.paste(tx, (round(x_t), round(ly - tx.height + dy)), tx)
            out.paste(tg, (round(x_t), round(ly - tx.height - tg.height - 22 + dy)), tg)
        label(low_tag, low_txt, cfg["low_t"], bar_x(0) + BAR_W / 2, BASE_Y - bar_h(0) - 300, "left", BASE_Y - bar_h(0))
        label(high_tag, high_txt, cfg["high_t"], bar_x(N - 1) + BAR_W / 2, BASE_Y - bar_h(N - 1), "right")
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
        for i, t in enumerate(cfg.get("preview_at") or [0.5, 1.6, 3.0, 4.6, T - 0.05]):
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
