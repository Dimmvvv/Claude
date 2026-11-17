#!/usr/bin/env python3
"""
Карточки-поляроиды поверх говорящей головы: фото персонажей выплывают сбоку, подпись от руки
на нижнем поле, «ретро-плёнка» (тёплый выцветший цвет, мягкая виньетка). Отдаётся на хромакее
(CapCut → «Хромакей») или превью поверх кадра с ведущим.

    python3 make_polaroids.py scene.json [--preview]

scene.json:
{
  "duration": 11, "out": "work/hook/polaroids.mp4", "bg": "chroma",
  "preview_bg": "work/hook/frame.webp",          # кадр с ведущим — только для превью
  "out_at": 10.3,                                 # все карточки уезжают обратно (необязательно)
  # у карточки "out": 6.5 — уходит одна в это время; "caption_style": "st" — красная антиква заглавными
  "cards": [
    {"img": "work/hook/karen.jpg", "crop": [x0, y0, x1, y1], "caption": "Карен",
     "t": 0.3, "at": [720, 820], "w": 900, "rot": -5},
    ...
  ]
}
at — центр карточки в кадре 3840×2160, w — ширина карточки, rot — наклон в покое (градусы).
Когда приходит следующая карточка, предыдущие отходят назад (меньше и темнее) — один фокус;
"back": false — не отходят и не тускнеют.
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
INK = (16, 21, 53)                 # brand синий #101535 — «чернила» подписи
PAPER = (248, 244, 233)            # brand бежевый #F8F4E9 — рамка поляроида
PAPER_OLD = ((242, 232, 208), (214, 194, 156))      # пожелтевшая бумага: светлый угол → тёмный
ST_RED, ST_RED_DARK = (196, 22, 24), (120, 10, 12)   # подпись в духе сериала (по просьбе владельца)


def caption_font(size):
    """Gilroy Medium Italic из brand/fonts (пара к акценту), иначе Inter Italic."""
    import glob
    root = os.path.join(HERE, "..", "brand", "fonts")
    for f in sorted(glob.glob(os.path.join(root, "Gilroy*Medium*Italic*"))):
        if f.lower().endswith((".ttf", ".otf")):
            return ImageFont.truetype(f, size)
    return ImageFont.truetype(os.path.join(HERE, "fonts", "inter", "Inter-Italic.otf"), size)


def retro(img):
    """Плёнка 80-х: ниже контраст, приподнятые тени, тёплый сдвиг, мягкая виньетка. Без зерна и бликов."""
    a = np.asarray(img, np.float32) / 255
    a = 0.05 + a * 0.92                                  # приподнять чёрное, притушить белое
    a = a * np.array([1.04, 1.0, 0.90])                  # тёплый
    g = a.mean(axis=2, keepdims=True)
    a = g + (a - g) * 0.88                               # чуть выцветший цвет
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    a = a * (1 - 0.15 * np.clip(r - 0.55, 0, 1) ** 1.5)[..., None]
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def aged_paper(w, h, seed):
    """Старая бумага поляроида: пожелтевший градиент, выгоревшие края, пятна, лёгкая фактура."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    g = (xx / w * 0.45 + yy / h * 0.55)[..., None]              # светлее сверху-слева
    a = np.array(PAPER_OLD[0], np.float32) * (1 - g) + np.array(PAPER_OLD[1], np.float32) * g
    e = np.minimum.reduce([xx, yy, w - 1 - xx, h - 1 - yy]) / (0.09 * w)
    a = a * (1 - 0.16 * np.clip(1 - e, 0, 1) ** 2)[..., None] # края темнее, в сепию
    a[..., 2] *= 1 - 0.06 * np.clip(1 - e, 0, 1)
    def blob(scale, amp):
        n = Image.fromarray((rng.random((h // scale + 2, w // scale + 2)) * 255).astype(np.uint8))
        n = n.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(scale * 0.6))
        return (np.asarray(n, np.float32) / 255 - 0.5) * amp
    a = a + (blob(max(8, w // 10), 22) + blob(max(3, w // 60), 8))[..., None] * np.array([1.0, 0.95, 0.8])
    a = a + rng.normal(0, 2.2, (h, w, 1))                      # фактура бумаги
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")


_FONTS = {}


def _st_font(size, cyr=True):
    """Playfair Display Bold: в файлах cyrillic нет цифр и знаков — для них файл latin."""
    k = (size, cyr)
    if k not in _FONTS:
        _FONTS[k] = ImageFont.truetype(os.path.join(
            HERE, "fonts", f"playfair-display-{'cyrillic' if cyr else 'latin'}-700-normal.woff"), size)
    return _FONTS[k]


def st_caption(card, c, txt, full=None):
    """Подпись в духе титров «Очень странных дел»: контрастная антиква заглавными, красная, с разрядкой.
    full — полный текст, по нему центрируется (чтобы печатающийся текст не ездил)."""
    w = card.width; d = ImageDraw.Draw(card)
    size = round(0.115 * w); sp = 0.06 * size
    fo = lambda ch: _st_font(size, mi.is_cyr(ch))
    full = (full or txt).upper(); txt = txt.upper()
    tw = sum(fo(ch).getlength(ch) for ch in full) + sp * (len(full) - 1)
    x = (w - tw) / 2
    for k, ch in enumerate(txt):
        # у счётчика ширина места — по итоговому символу, чтобы цифры не толкали соседей
        adv = fo(full[k]).getlength(full[k]) if k < len(full) else fo(ch).getlength(ch)
        cw = fo(ch).getlength(ch)
        d.text((x + (adv - cw) / 2, c["_cap_y"]), ch, font=fo(ch), fill=ST_RED, anchor="lm",
               stroke_width=max(1, w // 400), stroke_fill=ST_RED_DARK)
        x += adv + sp


_GLYPHS = {}


def _reel_glyph(ch, size, sw):
    """Символ барабана, выровненный по высоте «?»: у Playfair цифры «старинные» (разной высоты),
    а PIL без libraqm не включает ровные цифры — поэтому подгоняем каждую по высоте и центру."""
    k = (ch, size, sw)
    if k not in _GLYPHS:
        def spr(g):
            f = _st_font(size, mi.is_cyr(g))
            im = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((size, size), g, font=f, fill=ST_RED, anchor="mm", stroke_width=sw, stroke_fill=ST_RED_DARK)
            return im.crop(im.getbbox())
        ref = spr("?").height
        im = spr(ch)
        if ch.isdigit():
            im = im.resize((max(1, round(im.width * ref / im.height)), ref), Image.LANCZOS)
        _GLYPHS[k] = im
    return _GLYPHS[k]


def reel_caption(card, c, u):
    """Подпись-барабан: каждый разряд прокручивает 0–9 по вертикали и тормозит на итоговом символе
    (как счётчик/игровой автомат). Знаки «$ , . пробел» стоят. Разряды встают слева направо."""
    r = c["caption_roll"]; fin = r["final"].upper()
    w = card.width; size = round(0.115 * w); sp = 0.06 * size
    fo = lambda ch: _st_font(size, mi.is_cyr(ch))
    adv = [fo(ch).getlength(ch) for ch in fin]
    x = (w - sum(adv) - sp * (len(fin) - 1)) / 2
    sw = max(1, w // 400)
    qh = _reel_glyph("?", size, sw).height
    lh = 1.25 * qh                                           # шаг барабана
    bh = int(1.7 * qh)                                       # окно барабана
    band = Image.new("RGBA", (w, bh), (0, 0, 0, 0)); d = ImageDraw.Draw(band)
    yc = bh / 2
    seq = "0123456789" * r.get("cycles", 2)
    t0, spin, step = r.get("start", 0.4), r.get("spin", 1.0), r.get("stagger", 0.12)
    k = 0
    for ch, a in zip(fin, adv):
        if ch in "$ ,.":
            d.text((x + a / 2, yc), ch, font=fo(ch), fill=ST_RED, anchor="mm", stroke_width=sw, stroke_fill=ST_RED_DARK)
        else:
            col = seq + ch                                    # последняя ячейка — итоговый символ
            q = M.ease_out((u - t0) / (spin + k * step))     # быстро крутится — плавно тормозит
            pos = q * (len(col) - 1)
            i = int(pos); fr = pos - i
            for j, off in ((i, -fr), (i + 1, 1 - fr)):
                if 0 <= j < len(col):
                    g = _reel_glyph(col[j], size, sw)
                    band.alpha_composite(g, (round(x + a / 2 - g.width / 2), round(yc + off * lh - g.height / 2)))
            k += 1
        x += a + sp
    # мягкие края окна: цифры уходят вверх/вниз в бумагу, а не обрезаются
    m = np.ones(bh, np.float32); e = int(0.22 * bh)
    m[:e] = np.linspace(0, 1, e); m[-e:] = np.linspace(1, 0, e)
    A = np.asarray(band.getchannel("A"), np.float32) * m[:, None]
    band.putalpha(Image.fromarray(A.astype(np.uint8)))
    card.alpha_composite(band, (0, int(c["_cap_y"] - yc)))


def caption_at(c, u):
    """Текст подписи в момент u (секунды от появления карточки)."""
    if c.get("caption_roll"):                                 # счётчик: цифры крутятся и встают на final
        r = c["caption_roll"]; fin = r["final"]
        t0, step, spin = r.get("start", 0.3), r.get("stagger", 0.12), r.get("spin", 0.7)
        if u < t0:
            return fin[0]
        import random
        rnd = random.Random(int(u / r.get("tick", 1 / 30)))   # tick — как часто меняются цифры
        out = ""
        for k, ch in enumerate(fin):
            if ch in "$ ,." or u > t0 + spin + k * step:
                out += ch
            else:
                out += str(rnd.randint(0, 9))
        return out
    if c.get("caption_type"):                                 # печатается по буквам
        n = int(max(0.0, u - c.get("type_start", 0.25)) * M.TYPE_CPS)
        return c["caption"][:n]
    return None


def make_card(c):
    w = int(c["w"])
    side = round(0.06 * w); top = side; bottom = round(0.24 * w)
    pw = w - 2 * side; ph = round(pw * c.get("aspect", 1.0))
    photo = Image.open(c["img"]).convert("RGB")
    if c.get("crop"):
        photo = photo.crop(tuple(c["crop"]))
    # заполнить окно фото с обрезкой по центру
    k = max(pw / photo.width, ph / photo.height)
    photo = photo.resize((max(pw, round(photo.width * k)), max(ph, round(photo.height * k))), Image.LANCZOS)
    ox, oy = (photo.width - pw) // 2, (photo.height - ph) // 2
    photo = retro(photo.crop((ox, oy, ox + pw, oy + ph)))
    hh = top + ph + bottom
    card = aged_paper(w, hh, int(c.get("seed", 7))) if c.get("paper") == "old" else Image.new("RGBA", (w, hh), PAPER + (255,))
    # лёгкая «бумага»: нижнее поле чуть темнее к краю, тонкая внутренняя тень у фото
    card.paste(photo, (side, top))
    d = ImageDraw.Draw(card)
    d.rectangle([side, top, side + pw - 1, top + ph - 1], outline=(150, 132, 104, 255), width=max(2, w // 300))
    c["_cap_y"] = top + ph + bottom * 0.52
    if c.get("caption_roll") or c.get("caption_type"):
        pass                                                  # рисуется покадрово
    elif c.get("caption") and c.get("caption_style") == "st":
        st_caption(card, c, c["caption"], c["caption"])
    elif c.get("caption"):
        f = caption_font(round(0.10 * w))
        d.text((w / 2, top + ph + bottom * 0.5), c["caption"], font=f, fill=INK, anchor="mm")
    return card


# Гирлянда как в «Очень странных делах»: провод провисает по верху поляроида, лампочки C9.
# Ярко-зелёных лампочек нет — карточки идут на хромакее.
BULB_COLORS = [(236, 52, 40), (255, 196, 60), (64, 120, 255), (255, 128, 36), (238, 78, 160), (255, 226, 170)]


def _bulb(rx, ry, col, lit, ss=4):
    """Спрайт лампочки (RGBA): цоколь сверху в (0,0) спрайта по центру, колба вниз."""
    R, Ry = rx * ss, ry * ss
    sw, sh = int(2 * R + 4 * ss), int(2.6 * Ry + 4 * ss)
    im = Image.new("RGBA", (sw, sh), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    cx = sw / 2; sock = 0.55 * Ry
    d.rounded_rectangle([cx - 0.55 * R, 0, cx + 0.55 * R, sock], radius=0.2 * R, fill=(34, 34, 38, 255))
    pts = []
    for k in range(64):
        th = 2 * math.pi * k / 64
        x = math.sin(th) * R
        y = -math.cos(th)                                   # -1 сверху … 1 снизу
        x *= 1 - 0.45 * max(0.0, y) ** 1.6                  # кончик к низу
        pts.append((cx + x, sock + Ry * (1 + y)))
    body = tuple(int(v * (1.0 if lit else 0.42)) for v in col) + (255,)
    d.polygon(pts, fill=body)
    if lit:                                                 # светлая сердцевина и блик
        core = tuple(min(255, int(v * 0.55 + 255 * 0.45)) for v in col) + (255,)
        d.ellipse([cx - 0.45 * R, sock + 0.5 * Ry, cx + 0.45 * R, sock + 1.6 * Ry], fill=core)
    d.ellipse([cx - 0.55 * R, sock + 0.35 * Ry, cx - 0.2 * R, sock + 0.9 * Ry], fill=(255, 255, 255, 120 if lit else 60))
    return im.resize((sw // ss, sh // ss), Image.LANCZOS)


def make_lights(card, w, seed):
    """Рисует провод на карточке; возвращает лампочки для покадрового зажигания."""
    import random
    rnd = random.Random(seed)
    d = ImageDraw.Draw(card)
    x0, x1, y0, sag = 0.035 * w, 0.965 * w, 0.028 * w, 0.06 * w
    wire = lambda u: (x0 + (x1 - x0) * u, y0 + sag * 4 * u * (1 - u) + 0.008 * w * math.sin(9 * u + seed))
    d.line([wire(k / 80) for k in range(81)], fill=(28, 28, 30, 255), width=max(3, round(0.006 * w)), joint="curve")
    bulbs = []
    n = 6
    rx, ry = 0.027 * w, 0.039 * w
    for k in range(n):
        u = (k + 0.5) / n
        bx, by = wire(u)
        col = BULB_COLORS[(k + seed) % len(BULB_COLORS)]
        ang = rnd.uniform(-14, 14) + (u - 0.5) * -30
        on = _bulb(rx, ry, col, True).rotate(ang, Image.BICUBIC, expand=True)
        off = _bulb(rx, ry, col, False).rotate(ang, Image.BICUBIC, expand=True)
        # центр спрайта смещён вниз от точки крепления
        r_off = 0.55 * ry + ry
        cx = bx - math.sin(math.radians(ang)) * r_off * 0.9
        cy = by + math.cos(math.radians(ang)) * r_off * 0.9
        pos = (round(cx - on.width / 2), round(cy - on.height / 2))
        card.alpha_composite(off, pos)
        G = round(0.13 * w)                                      # ореол — окрашивает бумагу/фото вокруг
        yy, xx = np.mgrid[-G:G + 1, -G:G + 1]
        halo = np.exp(-(xx ** 2 + yy ** 2) / (2 * (0.45 * G) ** 2)).astype(np.float32)
        bulbs.append(dict(on=on, pos=pos, c=(round(cx), round(cy)), G=G, halo=halo,
                          col=np.array(col, np.float32), k=k, ph=rnd.uniform(0, 6.28), per=rnd.uniform(1.4, 2.4)))
    return bulbs


def light_up(base, bulbs, bright):
    """base — карточка с выключенными лампочками; bright — яркость каждой 0..1."""
    if max(bright) <= 0.01:
        return base
    a = np.asarray(base, np.float32).copy()
    H_, W_ = a.shape[:2]
    for b, v in zip(bulbs, bright):
        if v <= 0.01:
            continue
        G = b["G"]; cx, cy = b["c"]
        ya, yb, xa, xb = max(0, cy - G), min(H_, cy + G + 1), max(0, cx - G), min(W_, cx + G + 1)
        h = b["halo"][ya - (cy - G):yb - (cy - G), xa - (cx - G):xb - (cx - G)][..., None] * (M.LIGHT_HALO * v)
        a[ya:yb, xa:xb, :3] = a[ya:yb, xa:xb, :3] * (1 - h) + b["col"] * h
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    for b, v in zip(bulbs, bright):
        if v > 0.01:
            s = b["on"].copy(); s.putalpha(s.getchannel("A").point(lambda q: int(q * v)))
            out.alpha_composite(s, b["pos"])
    return out


def build(cfg, bg_img):
    T = cfg["duration"]
    cards = []
    for i, c in enumerate(cfg["cards"]):
        c = dict(c)
        im = make_card(c)
        bulbs = make_lights(im, int(c["w"]), i * 3 + 1) if cfg.get("lights", True) else []
        shd = None
        if cfg.get("bg", "chroma") != "chroma":                  # мягкая тень (на хромакее не рисуем)
            pad = int(0.08 * im.width)
            sa = Image.new("L", (im.width + 2 * pad, im.height + 2 * pad), 0)
            sa.paste(im.getchannel("A").point(lambda v: int(v * 0.6)), (pad, pad))
            shd = sa.filter(ImageFilter.GaussianBlur(0.03 * im.width))
        cards.append(dict(c, im=im, i=i, bulbs=bulbs, shd=shd))
    t_out = cfg.get("out_at")
    back_shift = cfg.get("back_shift", M.POLA_BACK_SHIFT)
    flick = cfg.get("flicker_at")

    def flicker(t):
        if flick is None or not (flick <= t < flick + 0.32):
            return 1.0
        u = t - flick
        for a, b, v in M.FLICKER:                                # «свет моргает», как в сериале
            if a <= u < b:
                return v
        return 1.0

    def frame(t):
        out = bg_img.copy()
        for c in cards:
            t0 = c["t"]; u = t - t0
            if u < 0:
                continue
            tx, ty = c["at"]; im = c["im"]
            s = 1.0
            if c.get("enter") == "drop":                           # «шлепок» сверху: крупнее → на место
                p = M.pop(u, M.STICKER_POP, M.OVERSHOOT)
                x, y = tx, ty
                s = 1 + M.DROP_SCALE * (1 - p)
                ang = c.get("rot", 0) + M.STICKER_TILT * 0.6 * (1 - M.ease_out(u / M.STICKER_TURN))
            else:
                din = c.get("in", M.POLA_IN)                       # «спокойнее»: длиннее и меньше перелёт
                p = M.pop(u, din, c.get("overshoot", M.OVERSHOOT_SMALL))
                sgn = 1 if c.get("enter") == "right" else -1
                sx = W + im.width * 0.8 if sgn > 0 else -im.width * 0.8
                if c.get("slide"):                                 # короткий въезд с проявлением (мягче)
                    sx = tx + sgn * c["slide"]
                x = sx + (tx - sx) * p
                y = ty + 60 * (1 - p)
                ang = c.get("rot", 0) + sgn * -c.get("tilt", M.POLA_TILT) * (1 - M.ease_out(u / (din * 1.25)))
            dark = 0.0
            # отходит назад, когда пришла следующая карточка (вторичное: позже и на 60% пути)
            nxt = [d for d in cards if d["i"] > c["i"]]
            if cfg.get("back", True) and nxt and (c.get("out") is None or nxt[0]["t"] < c["out"]):
                q = M.ease((t - nxt[0]["t"] - M.POLA_BACK_DELAY) / cfg.get("back_dur", M.POLA_BACK))
                s -= M.POLA_BACK_SCALE * q
                x -= back_shift[0] * q; y -= back_shift[1] * q
                dark = cfg.get("back_dark", M.POLA_BACK_DARK) * q
            # фон: покачивание < 5% главного движения
            ang += M.FACE_SWAY * 0.8 * math.sin(2 * math.pi * (t - t0) / M.FACE_SWAY_PERIOD + c["i"])
            y += 6 * math.sin(2 * math.pi * (t - t0) / (M.FACE_SWAY_PERIOD * 1.3) + c["i"])
            # уход
            co = c.get("out")
            e = 0.0
            if co is not None and t > co:                         # своя карточка уходит одна
                e = M.ease_in((t - co) / M.POLA_OUT)
            elif t_out is not None and t > t_out:
                k = len(cards) - 1 - c["i"]                       # верхняя уходит первой
                e = M.ease_in((t - t_out - k * M.STAGGER_ITEM) / M.POLA_OUT)
            if e > 0:                                             # уходит туда, откуда пришла
                if c.get("enter") == "right":
                    x += (W - x + im.width) * e; ang += 8 * e
                else:
                    x -= (x + im.width) * e; ang -= 8 * e
            if cfg.get("drift"):        # медленный наезд — только карточки; фон стоит, иначе сетка рябит
                z = 1 + M.DRIFT * 0.8 * (t / T)
                x = W / 2 + (x - W / 2) * z; y = H / 2 + (y - H / 2) * z; s *= z
            if x < -im.width * 1.5 or x > W + im.width * 1.5:
                continue
            # лампочки загораются по одной после посадки, потом едва заметно мерцают
            br = []
            for b in c["bulbs"]:
                din = c.get("in", M.POLA_IN)
                v = M.ease_out((u - din - b["k"] * M.LIGHT_STAGGER) / c.get("light_on", M.LIGHT_ON))
                ul = u - din - b["k"] * M.LIGHT_STAGGER
                if c.get("click", True) and 0.0 < ul < 0.22 and int(ul / 0.055) % 2 == 1:   # «щелчок» при включении
                    v *= 0.35
                v *= 1 - M.LIGHT_FLICKER + M.LIGHT_FLICKER * math.sin(2 * math.pi * t / b["per"] + b["ph"])
                br.append(max(0.0, v))
            ci = light_up(im, c["bulbs"], br) if br else im
            cap = None if (c.get("caption_roll") or {}).get("mode") == "reel" else caption_at(c, u)
            if (c.get("caption_roll") or {}).get("mode") == "reel":
                if ci is im:
                    ci = im.copy()
                reel_caption(ci, c, u)
            if cap:
                if ci is im:
                    ci = im.copy()
                st_caption(ci, c, cap, c["caption_roll"]["final"] if c.get("caption_roll") else c["caption"])
            if dark > 0:
                a0 = ci.getchannel("A")
                rgb = Image.eval(ci.convert("RGB"), lambda v: int(v * (1 - dark)))
                ci = rgb.convert("RGBA"); ci.putalpha(a0)
            w2, h2 = max(2, round(ci.width * s)), max(2, round(ci.height * s))
            if s != 1:
                ci = ci.resize((w2, h2), Image.LANCZOS)
            ci = ci.rotate(ang, Image.BICUBIC, expand=True)
            op = M.ease_out(u / c["fade"]) if c.get("fade") else 1.0   # прозрачность не пружинит
            if op < 1:
                ci.putalpha(ci.getchannel("A").point(lambda v: int(v * op)))
            if c["shd"] is not None:
                lift = 1 - M.ease_out(u / M.STICKER_LAND)
                sh = c["shd"]; ss = s * (1 + 0.06 * lift)
                sh = sh.resize((max(2, round(sh.width * ss)), max(2, round(sh.height * ss))), Image.BILINEAR)
                sh = sh.rotate(ang, Image.BILINEAR, expand=True)
                if op < 1:
                    sh = sh.point(lambda v: int(v * op))
                dy = (0.015 + 0.04 * lift) * ci.height
                out.paste((0, 0, 0), (round(x - sh.width / 2), round(y - sh.height / 2 + dy)), sh)
            out.paste(ci, (round(x - ci.width / 2), round(y - ci.height / 2)), ci)
        f = flicker(t)
        if f < 1:
            out = Image.eval(out, lambda v: int(v * f))
        return out

    return frame


_F = None


def scene_bg(cfg):
    """Фон сцены: хромакей, vignette-red (основной фон вставок, файл в brand/backgrounds)
    или фон бренда с сеткой (grid-red и т.п.) + мягкая виньетка."""
    v = cfg.get("bg", "chroma")
    if v == "chroma":
        return Image.new("RGB", (W, H), mi.CHROMA)
    if v.startswith("vignette-"):                     # готовый фон вставок: brand/backgrounds/vignette_<цвет>.png
        f = os.path.join(HERE, "..", "brand", "backgrounds", f"vignette_{v[9:]}.png")
        if os.path.exists(f):
            return Image.open(f).convert("RGB").resize((W, H))
        v = "grid-" + v[9:]
    mi.set_format("long")
    bg = mi.load_bg(v, cfg.get("title", "")).convert("RGB").resize((W, H))
    a = np.asarray(bg, np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    a *= (1 - 0.45 * np.clip(r - 0.45, 0, 1) ** 1.4)[..., None]
    return Image.fromarray(a.astype(np.uint8))


def _init(cfg):
    global _F
    _F = build(cfg, scene_bg(cfg))


def _render(t):
    return _F(t).tobytes()


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    T = cfg["duration"]
    stem = os.path.splitext(cfg["out"])[0]
    if "--preview" in sys.argv:
        pb = cfg.get("preview_bg")
        bg = Image.open(pb).convert("RGB").resize((W, H), Image.LANCZOS) if pb else scene_bg(cfg)
        frame = build(cfg, bg)
        ts = cfg.get("preview_at") or [c["t"] + d for c in cfg["cards"] for d in (0.15, 0.3, 1.0)] + \
            ([cfg["out_at"] + 0.2] if cfg.get("out_at") else []) + [T - 0.05]
        for i, t in enumerate(ts):
            p = f"{stem}_preview_{i}.png"; frame(t).resize((W // 2, H // 2), Image.LANCZOS).save(p)
            print("->", p, f"t={t:.2f}")
        return
    n = int(round(T * FPS))
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                           "-pix_fmt", "yuv420p", "-movflags", "+faststart", cfg["out"]], stdin=subprocess.PIPE)
    from multiprocessing import Pool
    with Pool(4, initializer=_init, initargs=(cfg,)) as pool:
        for i, buf in enumerate(pool.imap(_render, [k / FPS for k in range(n)], chunksize=4)):
            ff.stdin.write(buf)
            if i % 60 == 0:
                print(f"\r{i}/{n}", end="", flush=True)
    ff.stdin.close(); ff.wait()
    print(f"\r{n}/{n} -> {cfg['out']}")


if __name__ == "__main__":
    main()
