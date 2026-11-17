#!/usr/bin/env python3
"""
«Проваливаемся в источник»: окно с первой картинкой (страница источника), маркер по заголовку,
камера влетает в заголовок — из глубины выплывает вторая картинка (данные) крупно, маркер по нужной
строке, остальное гаснет, медленный доезд к строке. Фон вставок, плашка, подпись «ИСТОЧНИК».

    python3 make_dive.py scene.json [--preview]

scene.json:
{
  "duration": 6.1, "out": "work/fred/fred_dive.mp4", "bg": "vignette-red", "title": "Очень странные дела",
  "source": "FRED, Unemployment Rate in Indiana",
  "a": {"img": "work/fred/fred.png", "w": 2900, "at": [1920, 1150], "hl": [44, 246, 708, 298], "hl_t": 0.7},
  "dive_t": 1.75,
  "b": {"img": "work/fred/table.png", "crop": [0, 650, 526, 1240], "w": 1150, "at": [1920, 1180],
        "hl": [48, 1003, 410, 1058], "hl_t": 3.3, "dim_t": 4.0}
}
"bg": "chroma" — оверлей на ведущего (без теней), "preview_bg" — кадр для превью; b.out — уход влево.
Без "a" (и dive_t) — только вторая картинка: окно вырастает в b.t, маркер, гаснет остальное, доезд.
b.pin: {"at": [x, y], "label": "Хоукинс", "t": 1.8} — точка на картинке (координаты до crop) и подпись;
b.emerge: true — вторая карточка вырастает прямо из области a.hl на первой и встаёт по центру (b.at);
"dive_zoom" — насколько приближать первую при провале (по умолчанию DIVE_ZOOM).
"mark": false у a/b — hl служит только фокусом камеры, без маркера и затемнения.
hl — прямоугольник маркера в пикселях исходной картинки (x0, y0, x1, y1); для b — в координатах до crop.
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import make_collage as mc  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
HL = mi.HL_COLOR / 255.0                     # фиолетовый маркер, как во вставках с переводом


class Card:
    def __init__(self, spec):
        im = Image.open(spec["img"]).convert("RGB")
        ox, oy = 0, 0
        if spec.get("crop"):
            ox, oy = spec["crop"][:2]; im = im.crop(tuple(spec["crop"]))
        self.ox, self.oy = ox, oy
        self.src = np.asarray(im, np.float32)
        bgc = np.median(self.src.reshape(-1, 3), axis=0)
        blur = np.asarray(im.filter(ImageFilter.GaussianBlur(max(1.5, im.width / 400))), np.float32)
        self.dimmed = blur * 0.38 + bgc * 0.62                # как гаснет текст во вставках
        x0, y0, x1, y1 = spec["hl"]
        self.hl = (x0 - ox, y0 - oy, x1 - ox, y1 - oy)
        self.fr = mc.frame_card(im.width, im.height, int(spec["w"]))
        self.k = self.fr["cw"] / im.width                    # пиксель исходника → пиксель карточки
        self.spec = spec

    def content(self, mark, dim):
        a = self.src
        x0, y0, x1, y1 = self.hl
        h, w = a.shape[:2]
        if dim > 0 and self.spec.get("mark", True):
            m = np.ones((h, w), np.float32); m[int(y0):int(y1), int(x0):int(x1)] = 0
            m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), np.float32) / 255
            a = a + (self.dimmed - a) * (m * dim)[..., None]
        if mark > 0 and self.spec.get("mark", True):         # маркер «шторкой» слева направо, под текстом
            xe = x0 + (x1 - x0) * mark
            m = np.zeros((h, w), np.float32)
            m[int(y0):int(y1), int(x0):int(math.ceil(xe))] = 1
            a = a * (1 - m[..., None] * (1 - HL))
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        img = img.resize((self.fr["cw"], self.fr["ch"]), Image.LANCZOS)
        card = Image.new("RGBA", self.fr["outer"].size, (255, 255, 255, 0))
        card.paste((255, 255, 255, 255), (0, 0), self.fr["outer"])
        card.paste(img, (self.fr["bw"], self.fr["bw"]), self.fr["inner"])
        return card

    def focus(self):
        """Центр выделения в координатах карточки."""
        x0, y0, x1, y1 = self.hl
        return self.fr["bw"] + (x0 + x1) / 2 * self.k, self.fr["bw"] + (y0 + y1) / 2 * self.k


def place(out, card, s, fx, fy, px, py, op, shadow=None, lift=0.0):
    """Кладёт карточку в масштабе s так, чтобы её точка (fx, fy) встала в (px, py) кадра.
    Режет только видимую часть — при сильном зуме не раздуваем картинку целиком."""
    if op <= 0.01:
        return
    if shadow is not None and op > 0.01:
        sh = shadow.resize((max(2, round(shadow.width * s)), max(2, round(shadow.height * s))), Image.BILINEAR)
        sh = sh.point(lambda v: int(v * op))
        cx = px + (card.width / 2 - fx) * s; cy = py + (card.height / 2 - fy) * s
        out.paste((0, 0, 0), (round(cx - sh.width / 2), round(cy - sh.height / 2 + (0.015 + 0.04 * lift) * card.height * s)), sh)
    l = max(0.0, fx - px / s); t = max(0.0, fy - py / s)
    r = min(card.width, fx + (W - px) / s); b = min(card.height, fy + (H - py) / s)
    if r <= l or b <= t:
        return
    box = (int(l), int(t), int(math.ceil(r)), int(math.ceil(b)))
    piece = card.crop(box)
    piece = piece.resize((max(1, round(piece.width * s)), max(1, round(piece.height * s))),
                         Image.LANCZOS if s < 1.5 else Image.BILINEAR)
    if op < 1:
        piece.putalpha(piece.getchannel("A").point(lambda v: int(v * op)))
    out.paste(piece, (round(px + (box[0] - fx) * s), round(py + (box[1] - fy) * s)), piece)


_PIN = {}


def draw_pin(out, x, y, u, pin, s, edge=None):
    """Точка-метка: падает сверху с перелётом, один мягкий «пинг»-круг, подпись каскадом букв справа.
    pin.callout — подпись выносится за правый край карточки, к ней от точки тянется тонкая линия."""
    import make_words as mw
    import make_polaroids as mp
    r = pin.get("r", 26) * s
    p = M.pop(u, M.PIN_DROP, M.OVERSHOOT)
    yy = y - M.PIN_FALL * (1 - min(1.0, p))                       # падает сверху
    sc = max(0.0, p)
    d = ImageDraw.Draw(out, "RGBA")
    pg = M.ease_out((u - 0.15) / M.PIN_PING)                      # один «пинг» после посадки
    if 0 < pg < 1:
        rr = r * (1 + 3.5 * pg)
        d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=mp.ST_RED + (int(200 * (1 - pg)),), width=max(2, round(5 * s)))
    if sc > 0:
        R = r * sc; ring = R * 1.35
        d.ellipse([x - ring, yy - ring, x + ring, yy + ring], fill=(255, 250, 240, 255))
        d.ellipse([x - R, yy - R, x + R, yy + R], fill=mp.ST_RED + (255,))
    # подпись
    key = (pin["label"], pin.get("size", 120))
    if key not in _PIN:
        _PIN[key] = mw.letter_sprites(pin["label"], pin.get("size", 120))
    letters = _PIN[key]; size = pin.get("size", 120)
    tw = letters[-1]["dx"] + letters[-1]["a"] / 2 - (letters[0]["dx"] - letters[0]["a"] / 2)
    lx0 = x + r * 2.2
    if pin.get("callout") and edge is not None:                   # выноска: линия от точки за край карточки
        lx0 = edge + M.PIN_CALLOUT_GAP
        ln = M.ease((u - M.PIN_LABEL_DELAY * 0.5) / M.PIN_LINE)
        if ln > 0:
            x1 = x + r * 1.6; x2 = x1 + (lx0 - 30 - x1) * ln
            d.line([x1, y, x2, y], fill=(248, 240, 224, 255), width=max(3, round(5 * s)))
    cx0 = lx0 + tw / 2 * s                                        # центр слова
    for k, L in enumerate(letters):
        v = u - M.PIN_LABEL_DELAY - (M.PIN_LINE * 0.6 if pin.get("callout") else 0) - k * M.WORD_STAGGER
        if v < 0:
            continue
        q = M.pop(v, M.WORD_IN, M.OVERSHOOT_SMALL)
        op = M.ease_out(v / M.WORD_FADE)
        ss = s * (M.WORD_FROM + (1 - M.WORD_FROM) * q)
        im = L["im"].resize((max(2, round(L["im"].width * ss)), max(2, round(L["im"].height * ss))), Image.LANCZOS)
        if op < 1:
            im.putalpha(im.getchannel("A").point(lambda a: int(a * op)))
        lx = cx0 + L["dx"] * s - im.width / 2
        ly = y + 0.36 * size * s - L["base"] * ss + M.WORD_RISE * size * s * (1 - q)
        out.paste(im, (round(lx), round(ly)), im)


def build(cfg, bg):
    T = cfg["duration"]
    A = Card(cfg["a"]) if cfg.get("a") else None          # без "a" — только таблица, без провала
    B = Card(cfg["b"])
    td = cfg.get("dive_t", 0.0)
    chroma = cfg.get("bg") == "chroma"                     # на хромакее тени не рисуем
    cap = None
    if cfg.get("source"):
        LAY = mi.LAYOUTS["long"]
        cap_label, cap_text, cap_line = mi.caption_colors(bg)
        cap = Image.new("RGBA", (W, 200), (0, 0, 0, 0)); cd = ImageDraw.Draw(cap)
        fl = ImageFont.truetype(mi.body_font_path(), 34); x = LAY["cap_x"]
        for c in "ИСТОЧНИК":
            cd.text((x, 100), c, font=fl, fill=cap_label, anchor="lm"); x += fl.getlength(c) + 6
        x += 28; cd.line([x, 70, x, 130], fill=cap_line, width=2); x += 32
        cd.text((x, 100), cfg["source"], font=ImageFont.truetype(mi.body_font_path(), 44), fill=cap_text, anchor="lm")
        cap_y = LAY["cap_y"]

    def a_geom(t):
        """Масштаб и положение точки фокуса первой карточки в момент t (+ прозрачность, доля провала)."""
        u = t - cfg["a"].get("t", 0.0)
        ax, ay = cfg["a"]["at"]
        cw, ch = A.fr["outer"].size
        fx, fy = A.focus()
        p = M.pop(u, M.WIN_POP, M.OVERSHOOT_SMALL)
        s = (M.WIN_FROM + (1 - M.WIN_FROM) * p) * (1 + 0.02 * min(1.0, t / max(td, 0.1)))
        op = M.ease_out(u / M.APPEAR)
        px0 = ax + (fx - cw / 2) * s; py0 = ay + (fy - ch / 2) * s + 40 * (1 - p)
        px, py, e = px0, py0, 0.0
        if t >= td:                                           # провал: зум в фокус с ускорением
            e = M.ease_in((t - td) / M.DIVE)
            s *= math.exp(math.log(cfg.get("dive_zoom", M.DIVE_ZOOM)) * e)
            px = px0 + (W / 2 - px0) * e; py = py0 + (H / 2 - py0) * e
            op *= 1 - M.ease((t - td - 0.4 * M.DIVE) / (0.6 * M.DIVE))   # прозрачность не пружинит
        return s, px, py, op, e

    emerge = None
    if A and cfg["b"].get("emerge"):
        # вторая карточка вырастает прямо из выделенной области первой (Индиана на карте США)
        tb0 = td + M.DIVE_B_DELAY
        sa, pxa, pya, _, _ = a_geom(tb0)
        x0, y0, x1, y1 = cfg["a"]["hl"]
        hl_h = (y1 - y0) * A.k * sa                              # высота области на экране
        emerge = (pxa, pya, hl_h / B.fr["outer"].size[1])

    def frame(t):
        out = bg.copy()
        if cap is not None:
            ca = M.ease_out((t - cfg.get("source_at", 0.5)) / M.CAPTION)
            if ca > 0:
                c = cap.copy(); c.putalpha(c.getchannel("A").point(lambda v: int(v * ca)))
                out.paste(c, (0, int(cap_y + 20 * (1 - ca))), c)
        # --- A: окно появляется, маркер по заголовку, потом камера влетает в заголовок
        u = t - cfg["a"].get("t", 0.0) if A else -1
        if A and u >= 0 and t < td + M.DIVE:
            ca = A.content(M.ease((t - cfg["a"]["hl_t"]) / M.HIGHLIGHT), 0.0)
            fx, fy = A.focus()
            s, px, py, op, e = a_geom(t)
            shadow = A.fr["shd"] if e < 0.2 else None
            place(out, ca, s, fx, fy, px, py, op, shadow, 1 - M.ease_out(u / M.STICKER_LAND))
        # --- B: данные выплывают из глубины, маркер по строке, остальное гаснет, медленный доезд
        tb = td + M.DIVE_B_DELAY if A else cfg["b"].get("t", 0.0)
        v = t - tb
        if v >= 0:
            bx, by = cfg["b"]["at"]
            cb = B.content(M.ease((t - cfg["b"]["hl_t"]) / cfg["b"].get("hl_dur", M.HIGHLIGHT_INSERT)),
                           M.ease((t - cfg["b"]["dim_t"]) / cfg["b"].get("dim_dur", M.DIM)))
            fx, fy = B.focus()
            if emerge:                                              # растёт из области на первой карте и встаёт по центру
                cw, ch = cb.width, cb.height
                fx, fy = cw / 2, ch / 2                             # якорь — центр карточки
                p = M.pop(v, M.DIVE_B_IN, M.OVERSHOOT_SMALL * 0.5)
                ex, ey, es = emerge
                s = es + (1 - es) * p
                q = M.ease_out(v / M.DIVE_B_IN)
                px = ex + (bx - ex) * q; py = ey + (by - ey) * q
                s *= 1 + M.DIVE_PUSH * 0.6 * M.ease((t - tb) / max(0.1, T - tb))   # только лёгкий наезд, по центру
                op = M.ease_out(v / M.APPEAR)
                place(out, cb, s, fx, fy, px, py, op, B.fr["shd"] if v > 0.25 else None, 1 - M.ease_out(v / M.STICKER_LAND))
                pin = cfg["b"].get("pin")
                if pin and t >= pin["t"]:
                    qx = B.fr["bw"] + (pin["at"][0] - B.ox) * B.k; qy = B.fr["bw"] + (pin["at"][1] - B.oy) * B.k
                    draw_pin(out, px + (qx - fx) * s, py + (qy - fy) * s, t - pin["t"], pin, s, px + (cw - fx) * s)
                return out
            if A:                                                   # выплывает из глубины после провала
                p = M.pop(v, M.DIVE_B_IN, M.OVERSHOOT_SMALL * 0.6)
                s = M.DIVE_B_FROM + (1 - M.DIVE_B_FROM) * p
            else:                                                   # просто окно: вырастает, как в make_collage
                p = M.pop(v, M.WIN_POP, M.OVERSHOOT_SMALL)
                s = M.WIN_FROM + (1 - M.WIN_FROM) * p
            push = M.ease((t - tb) / max(0.1, T - tb))               # медленный доезд к строке
            s *= 1 + M.DIVE_PUSH * push
            px = bx + (fx - cb.width / 2) * s; py = by + (fy - cb.height / 2) * s
            if not chroma:                                          # на оверлее карточка стоит на своём месте
                px += (W / 2 - px) * 0.35 * push; py += (H / 2 + 60 - py) * 0.35 * push
            op = M.ease_out(v / (M.DIVE_B_FADE if A else M.APPEAR))
            bo = cfg["b"].get("out")
            if bo is not None and t > bo:                           # уход влево (оверлей на ведущем)
                e = M.ease_in((t - bo) / M.POLA_OUT)
                px -= (px + cb.width * s) * e
            place(out, cb, s, fx, fy, px, py, op, None if chroma else B.fr["shd"], 1 - M.ease_out(v / M.STICKER_LAND))
            pin = cfg["b"].get("pin")
            if pin and t >= pin["t"]:
                # точка на карте в координатах кадра
                qx = B.fr["bw"] + (pin["at"][0] - B.ox) * B.k; qy = B.fr["bw"] + (pin["at"][1] - B.oy) * B.k
                edge = px + (cb.width - fx) * s                       # правый край карточки в кадре
                draw_pin(out, px + (qx - fx) * s, py + (qy - fy) * s, t - pin["t"], pin, s, edge)
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
        pb = cfg.get("preview_bg")
        frame = build(cfg, Image.open(pb).convert("RGB").resize((W, H), Image.LANCZOS) if pb else mc.scene_bg(cfg))
        for i, t in enumerate(cfg.get("preview_at") or [0.3, 1.3, 1.95, 2.2, 2.6, 3.8, T - 0.05]):
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
