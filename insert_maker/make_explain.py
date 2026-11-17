#!/usr/bin/env python3
"""
Объяснение «что значит пересчёт»: сверху формула (плашка → стрелка с подписью → плашка), ниже две
фразы — верная (жёлтый маркер + галочка) и неверная (красное зачёркивание + крестик, гаснет).
Стикеры по бокам. Фон вставок, фирменная плашка.

    python3 make_explain.py scene.json [--preview]

scene.json:
{
  "duration": 8, "out": "work/explain/explain.mp4", "bg": "vignette-red", "title": "Очень странные дела",
  "from": "$ 1980-х", "arrow": "с учётом инфляции", "to": "$ и ₽ сегодня",
  "yes": "«Сколько бы эти деньги стоили сейчас»", "no": "«Сколько эта работа приносит сегодня»",
  "stickers": [...],
  "from_t": 0.7, "arrow_t": 1.3, "to_t": 1.9, "yes_t": 3.0, "no_t": 5.0, "strike_t": 5.9
}
"""
import json, math, os, sys, subprocess
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_levels as ml  # noqa: E402
import make_polaroids as mp  # noqa: E402
import make_collage as mc  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
CREAM, HL_YELLOW = ml.CREAM, ml.HL_YELLOW
YELLOW_PLATE = (252, 205, 3)          # бренд: жёлтый, на тёмном — плашка 40%
RED = (226, 52, 44)


def chip(text):
    """Плашка-ярлык: текст Playfair заглавными на полупрозрачной светлой подложке со скруглением."""
    # в Playfair нет «₽» — этот знак фирменным шрифтом
    fn = lambda sz, ch: ml.body_font(int(sz * 0.95)) if ch == "₽" else ml.st_font(sz, ch)
    t = ml.text_sprite(text.upper(), fn, 104, CREAM, sp=0.05, lining=True)
    px, py = 60, 40
    im = Image.new("RGBA", (t.width + 2 * px, t.height + 2 * py), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, im.width - 1, im.height - 1], im.height // 2,
                                         fill=(255, 255, 255, 30), outline=CREAM + (120,), width=3)
    im.alpha_composite(t, (px, py))
    return im


def build(cfg, bg):
    stickers = ml.load_stickers(cfg["stickers"])
    c_from, c_to = chip(cfg["from"]), chip(cfg["to"])
    arrow_lbl = ml.text_sprite(cfg["arrow"], lambda sz, ch: ml.body_font(sz), 56, CREAM)
    yes = ml.text_sprite(cfg["yes"], lambda sz, ch: ml.body_font(sz), 86, CREAM)
    no = ml.text_sprite(cfg["no"], lambda sz, ch: ml.body_font(sz), 86, CREAM)
    row_y = 680                                   # центр строки формулы
    gap = max(420, arrow_lbl.width + 160)         # стрелка не короче своей подписи
    tot = c_from.width + gap + c_to.width
    xf = W / 2 - tot / 2; xa0 = xf + c_from.width + 40; xa1 = xf + c_from.width + gap - 40; xt = xf + c_from.width + gap
    text_x = W / 2 - max(yes.width, no.width) / 2 + 80      # фразы — по общему левому краю, иконки слева
    yes_y, no_y = 1180, 1530

    def frame(t):
        out = bg.copy()
        d = ImageDraw.Draw(out, "RGBA")
        ml.draw_stickers(out, stickers, t)

        def pop_in(im, x, y, t0):                  # проявление + небольшой подъём, текст не пружинит
            u = t - t0
            if u <= 0:
                return
            q = M.ease_out(u / M.CARD_FADE)
            im2 = ml.fade(im, q)
            out.paste(im2, (round(x), round(y + 30 * (1 - q))), im2)

        # --- формула: плашка → стрелка (тянется) → плашка
        pop_in(c_from, xf, row_y - c_from.height / 2, cfg["from_t"])
        u = t - cfg["arrow_t"]
        if u > 0:
            q = M.ease(u / M.LEVEL_AXIS)
            xe = xa0 + (xa1 - xa0) * q
            d.line([xa0, row_y, xe, row_y], fill=CREAM + (220,), width=6)
            if q > 0.85:
                d.polygon([(xe + 8, row_y), (xe - 30, row_y - 20), (xe - 30, row_y + 20)], fill=CREAM + (220,))
            pop_in(arrow_lbl, (xa0 + xa1) / 2 - arrow_lbl.width / 2, row_y - 110, cfg["arrow_t"] + 0.2)
        pop_in(c_to, xt, row_y - c_to.height / 2, cfg["to_t"])

        # --- верная фраза: появляется, жёлтая плашка шторкой под ней, галочка рисуется
        u = t - cfg["yes_t"]
        if u > 0:
            mk = M.ease((u - 0.35) / M.HIGHLIGHT_INSERT)
            if mk > 0:
                x0, y0 = text_x - 24, yes_y - 18
                x1 = x0 + (yes.width + 48) * mk
                d.rounded_rectangle([x0, y0, x1, y0 + yes.height + 36], 14, fill=YELLOW_PLATE + (int(255 * 0.4),))
            pop_in(yes, text_x, yes_y, cfg["yes_t"])
            ck = M.ease((u - 0.9) / 0.4)
            if ck > 0:                               # галочка
                cx, cy, r = text_x - 120, yes_y + yes.height / 2, 46
                pts = [(cx - r, cy), (cx - r * 0.3, cy + r * 0.7), (cx + r, cy - r * 0.8)]
                seg = ck * 2
                p1 = pts[1] if seg >= 1 else (pts[0][0] + (pts[1][0] - pts[0][0]) * seg, pts[0][1] + (pts[1][1] - pts[0][1]) * seg)
                d.line([pts[0], p1], fill=HL_YELLOW + (255,), width=14, joint="curve")
                if seg > 1:
                    s2 = seg - 1
                    p2 = (pts[1][0] + (pts[2][0] - pts[1][0]) * s2, pts[1][1] + (pts[2][1] - pts[1][1]) * s2)
                    d.line([pts[1], p2], fill=HL_YELLOW + (255,), width=14, joint="curve")

        # --- неверная фраза: появляется, потом зачёркивается красной линией, крестик, гаснет
        u = t - cfg["no_t"]
        if u > 0:
            dim = M.ease((t - cfg["strike_t"] - 0.3) / M.DIM)
            q = M.ease_out(u / M.CARD_FADE)
            im2 = ml.fade(no, q * (1 - 0.55 * dim))
            out.paste(im2, (round(text_x), round(no_y + 30 * (1 - q))), im2)
            sk = M.ease((t - cfg["strike_t"]) / 0.45)
            if sk > 0:
                ly = no_y + no.height * 0.55
                d.line([text_x - 20, ly, text_x - 20 + (no.width + 40) * sk, ly], fill=RED + (255,), width=12)
            xk = M.pop(t - cfg["strike_t"] - 0.35, 0.35, M.OVERSHOOT_SMALL)    # крестик «шлёпается»
            if xk > 0:
                cx, cy, r = text_x - 120, no_y + no.height / 2, 40 * xk
                d.line([cx - r, cy - r, cx + r, cy + r], fill=RED + (255,), width=14)
                d.line([cx - r, cy + r, cx + r, cy - r], fill=RED + (255,), width=14)
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
        for i, t in enumerate(cfg.get("preview_at") or [1.0, 2.5, 4.5, 6.6, T - 0.05]):
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
