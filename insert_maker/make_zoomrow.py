#!/usr/bin/env python3
"""
Окно с документом целиком → маркер по строке → «приближение»: окно плавно меняет форму на широкую
полосу вокруг строки, а камера внутри него приближается к ней; остальное гаснет. Фон вставок,
фирменная плашка, подпись «ИСТОЧНИК». Фон стоит, двигается только окно.

    python3 make_zoomrow.py scene.json [--preview]

scene.json:
{
  "duration": 3.5, "out": "work/minwage/minwage.mp4", "bg": "vignette-red", "title": "Очень странные дела",
  "source": "Federal Minimum Wage Rates",
  "img": "work/minwage/table.png",
  "h0": 1600,                         # высота окна в начале (вся картинка), px
  "view": [62, 918, 878, 1092],       # область картинки в конце (x0, y0, x1, y1)
  "w1": 3000,                         # ширина окна в конце, px
  "at": [1920, 1150],
  "hl": [70, 996, 655, 1022], "hl_t": 0.7, "zoom_t": 1.3, "dim_t": 1.5
}
"bands": [{"rect": [...], "t": 1.9, "dir": "h"|"v"}] — мягкие полосы вдоль строки / вниз по колонке (перекрестье);
marks[i].bold: true — цифры в выделенной ячейке становятся жирнее (вместе с появлением маркера);
"pad_bottom": N — пустое поле снизу; "overlays": [{"img", "crop": [x0,y0,x1,y1], "scale", "x", "y", "t"}] — кусок таблицы
  с другого скрина ложится поверх на (x, y) таблицы (scale и x подбираются по колонкам), проявляясь с тенью;
"views": [{"t", "dur", "view": [x0,y0,x1,y1]}, ...] — камера идёт по видам; виды одной ширины и высоты = плавный «переезд»;
"patches": [{"rect": [x0,y0,x1,y1], "text": "перевод", "t": 1.7} | {"rect", "img": "<префикс>_ru.png" (перевод целой страницей, --dump), "t"}] — надпись в таблице заменяется переводом (жирный Roboto);
"at1": [x, y] — куда окно переезжает вместе с приближением;
"compare": {"t", "y", "rows": [{"label", "value", "color": "cream"|"yellow"}], "gap_t", "note", "sub", "note_t"} —
  сравнение полосами под окном (длины строго по значениям).
"fly": {"y", "line": [{"text", "num": true, "src": [x0,y0,x1,y1], "color", "t"} | {"text", "t"}],
        "accent": {"text", "t", "y"}} — числа перелетают из ячеек в строку под окном, затем акцентный саб.
"wipe": {"rect": [x0,y0,x1,y1], "t", "dur"} — линии графика прорисовываются слева направо;
"bars": [{"rect": [x0,y0,x1,y1], "t", "dur", "src_x"}] — столбики диаграммы вырастают снизу (src_x — пустой участок графика);
"stickers": [{"img", "at": [x, y], "w", "rot", "t"}] — наклейки на кадре (шлепок, тень, покачивание), вне окна;
"callout": {"text": "$180 в неделю", "at": [x, y], "t": 4.3} — выноска под окном с линией от точки картинки.
Несколько выделений по очереди: "marks": [{"hl": [x0, y0, x1, y1], "t": 2.0}, ...] вместо hl/hl_t —
тогда в конце гаснет всё, кроме выделенных мест.
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import make_collage as mc  # noqa: E402
import make_levels as ml  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
HL = mi.HL_COLOR / 255.0


def caption_layer(cfg, bg):
    LAY = mi.LAYOUTS["long"]
    cap_label, cap_text, cap_line = mi.caption_colors(bg)
    cap = Image.new("RGBA", (W, 200), (0, 0, 0, 0)); cd = ImageDraw.Draw(cap)
    fl = ImageFont.truetype(mi.body_font_path(), 34); x = LAY["cap_x"]
    for c in "ИСТОЧНИК":
        cd.text((x, 100), c, font=fl, fill=cap_label, anchor="lm"); x += fl.getlength(c) + 6
    x += 28; cd.line([x, 70, x, 130], fill=cap_line, width=2); x += 32
    cd.text((x, 100), cfg["source"], font=ImageFont.truetype(mi.body_font_path(), 44), fill=cap_text, anchor="lm")
    return cap, LAY["cap_y"]


_CO = {}


def draw_callout(out, co, u, px, py, win_bottom):
    """Крупная подпись-ярлык под окном (Playfair, светло-жёлтый) и тонкая линия от ячейки к ней."""
    import make_levels as ml
    if "im" not in _CO:
        fn = lambda sz, ch: ml.body_font(int(sz * 0.95)) if ch == "₽" else ml.st_font(sz, ch)
        tx = ml.text_sprite(co["text"].upper(), fn, co.get("size", 120), ml.HL_YELLOW, sp=0.04, lining=True)
        padx, pady = 60, 38
        im = Image.new("RGBA", (tx.width + 2 * padx, tx.height + 2 * pady), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle([0, 0, im.width - 1, im.height - 1], im.height // 2,
                                             fill=(252, 205, 3, int(255 * 0.4)))      # бренд: жёлтая плашка 40%
        im.alpha_composite(tx, (padx, pady))
        _CO["im"] = im
    im = _CO["im"]
    d = ImageDraw.Draw(out, "RGBA")
    ln = M.ease(u / M.PIN_LINE)
    top = win_bottom + co.get("gap", 110)
    d.ellipse([px - 14, py - 14, px + 14, py + 14], outline=(250, 227, 145, int(255 * min(1, u / 0.15))), width=5)
    d.line([px, py + 16, px, py + 16 + (top - py - 16) * ln], fill=(250, 227, 145, 230), width=5)
    v = u - M.PIN_LINE * 0.7
    if v > 0:
        q = M.pop(v, M.WORD_IN, M.OVERSHOOT_SMALL); op = M.ease_out(v / M.WORD_FADE)
        s = 0.7 + 0.3 * q
        c = im.resize((max(2, round(im.width * s)), max(2, round(im.height * s))), Image.LANCZOS)
        c.putalpha(c.getchannel("A").point(lambda a: int(a * op)))
        x = min(max(px - c.width / 2, 120), out.width - 120 - c.width)
        out.paste(c, (round(x), round(top + (im.height - c.height) / 2)), c)


_CMP = {}


def draw_compare(out, c, t):
    """Сравнение под окном: полосы в точной пропорции значений растут каскадом, цифры докручиваются,
    у меньшей — контур недостающей части, ниже вывод (ярлык) и пояснение."""
    import make_levels as ml
    d = ImageDraw.Draw(out, "RGBA")
    rows = c["rows"]; vmax = max(r["value"] for r in rows)
    x_lab, x_bar, L = c.get("x_label", 700), c.get("x_bar", 1180), c.get("length", 2000)
    bh, gap = c.get("bar_h", 120), c.get("row_gap", 230)
    if "lab" not in _CMP:
        _CMP["lab"] = [ml.text_sprite(r["label"], lambda sz, ch: ml.body_font(sz), 84, ml.CREAM) for r in rows]
        _CMP["note"] = ml.text_sprite(c["note"].upper(), lambda sz, ch: ml.st_font(sz, ch), 120, ml.HL_YELLOW, sp=0.04, lining=True)
        _CMP["sub"] = ml.text_sprite(c["sub"], lambda sz, ch: ml.body_font(sz), 72, ml.CREAM)
    cols = {"cream": ml.CREAM, "yellow": ml.HL_YELLOW}
    for i, r in enumerate(rows):
        t0 = c["t"] + i * M.CMP_STAGGER
        u = t - t0
        if u <= 0:
            continue
        y = c["y"] + i * gap
        op = M.ease_out(u / M.CARD_FADE)
        lab = ml.fade(_CMP["lab"][i], op)
        out.paste(lab, (round(x_bar - 50 - lab.width), round(y + bh / 2 - lab.height / 2)), lab)
        g = M.ease_out(u / M.CMP_GROW)                          # полоса растёт; длина — строго по значению
        w = L * r["value"] / vmax * g
        if w > 2:
            d.rounded_rectangle([x_bar, y, x_bar + w, y + bh], 16, fill=cols[r.get("color", "cream")] + (235,))
        val = "$" + str(int(round(r["value"] * g)))              # цифра докручивается вместе с полосой
        vs = ml.text_sprite(val, lambda sz, ch: ml.st_font(sz, ch), 96, ml.CREAM, lining=True)
        vs = ml.fade(vs, op)
        out.paste(vs, (round(x_bar + w + 40), round(y + bh / 2 - vs.height / 2)), vs)
        if r["value"] < vmax:                                   # недостающая часть — пунктирный контур
            q = M.ease((t - c["gap_t"]) / 0.5)
            if q > 0:
                x1 = x_bar + L * r["value"] / vmax; x2 = x1 + (x_bar + L - x1) * q
                a = int(170 * q)
                k = x1
                while k < x2:                                    # пунктир по верху и низу
                    d.line([k, y, min(k + 26, x2), y], fill=ml.CREAM + (a,), width=4)
                    d.line([k, y + bh, min(k + 26, x2), y + bh], fill=ml.CREAM + (a,), width=4)
                    k += 44
                if q >= 1:
                    d.line([x2, y, x2, y + bh], fill=ml.CREAM + (a,), width=4)
    u = t - c["note_t"]
    if u > 0:
        q = M.pop(u, M.WORD_IN, M.OVERSHOOT_SMALL); op = M.ease_out(u / M.WORD_FADE)
        y = c["y"] + len(rows) * gap + 30
        n = ml.fade(_CMP["note"], op)
        out.paste(n, (round(x_bar), round(y + 30 * (1 - q))), n)
        v = u - 0.35
        if v > 0:
            sb = ml.fade(_CMP["sub"], M.ease_out(v / M.CARD_FADE))
            out.paste(sb, (round(x_bar), round(y + n.height + 34)), sb)


_FLY = {}


def mp_caption_font(size):
    import make_polaroids as mp
    return mp.caption_font(size)


def draw_fly(out, f, t, to_screen):
    """Строка сравнения ниже окна: числа берутся из ячеек таблицы и по дуге перелетают в свои места,
    вокруг проявляются слова; в конце — акцентный «саб» по словам."""
    import make_levels as ml
    if "parts" not in _FLY:
        cols = {"cream": ml.CREAM, "yellow": ml.HL_YELLOW}
        parts = []
        fonts = {"st": lambda sz, ch: ml.st_font(sz, ch),               # Playfair (в духе сериала)
                 "body": lambda sz, ch: ml.body_font(sz),               # бренд: Gilroy Regular / Inter
                 "italic": lambda sz, ch: mp_caption_font(sz)}          # бренд: Gilroy Medium Italic / Inter Italic
        for it in f["line"]:
            fn = fonts[it.get("font", f.get("font", "st"))]
            if it.get("num"):
                sp = ml.text_sprite(it["text"], fn, f.get("num_size", 210), cols[it.get("color", "cream")],
                                    lining=it.get("font", f.get("font", "st")) == "st")
            else:
                sp = ml.text_sprite(it["text"], fn, it.get("size", f.get("word_size", 100)),
                                    cols[it.get("color", "cream")])
            parts.append(dict(it, im=sp))
        gap = f.get("gap", 60)
        tot = sum(p["im"].width for p in parts) + gap * (len(parts) - 1)
        x = out.width / 2 - tot / 2
        for p in parts:                                          # все части центрируются по одной высоте
            p["x"], p["y"] = x, f["y"] - p["im"].height / 2; x += p["im"].width + gap
        _FLY["parts"] = parts
        words = f["accent"]["text"].upper().split()
        afn = (lambda sz, ch: ml.body_font(sz)) if f["accent"].get("font") == "body" else (lambda sz, ch: ml.st_font(sz, ch))
        _FLY["acc"] = [ml.text_sprite(w, afn, f["accent"].get("size", 140), ml.HL_YELLOW,
                                      sp=f["accent"].get("tracking", 0.04), lining=f["accent"].get("font") != "body")
                       for w in words]
    d = ImageDraw.Draw(out, "RGBA")
    for p in _FLY["parts"]:
        if p.get("num"):
            u = t - p["t"]
            if u <= 0:
                continue
            q = M.ease(u / M.FLY)
            x0, y0, x1, y1 = to_screen(*p["src"])
            s0 = (y1 - y0) * 1.25 / p["im"].height               # старт — размер цифры в ячейке
            sc = s0 + (1 - s0) * q
            sx, sy = (x0 + x1) / 2, (y0 + y1) / 2                 # центр: из ячейки → в своё место, по дуге
            ex, ey = p["x"] + p["im"].width / 2, p["y"] + p["im"].height / 2
            mx = sx + (ex - sx) * q
            my = sy + (ey - sy) * q - M.FLY_ARC * math.sin(math.pi * q)
            im = p["im"].resize((max(2, round(p["im"].width * sc)), max(2, round(p["im"].height * sc))), Image.LANCZOS)
            im = ml.fade(im, min(1.0, u / 0.12))
            out.paste(im, (round(mx - im.width / 2), round(my - im.height / 2)), im)
        else:
            u = t - p["t"]
            if u <= 0:
                continue
            q = M.ease_out(u / M.CARD_FADE)
            im = ml.fade(p["im"], q)
            out.paste(im, (round(p["x"]), round(p["y"] + 24 * (1 - q))), im)
    a = f["accent"]                                              # акцентный саб: слова по одному
    acc = _FLY["acc"]; sp = a.get("word_gap", 0.32) * a.get("size", 140)
    tot = sum(w.width for w in acc) + sp * (len(acc) - 1)
    x = out.width / 2 - tot / 2
    for k, w in enumerate(acc):
        u = t - a["t"] - k * M.ACCENT_STAGGER
        if u > 0:
            q = M.pop(u, M.WORD_IN, M.OVERSHOOT_SMALL); op = M.ease_out(u / M.WORD_FADE)
            s = M.WORD_FROM + (1 - M.WORD_FROM) * q
            im = w.resize((max(2, round(w.width * s)), max(2, round(w.height * s))), Image.LANCZOS)
            im = ml.fade(im, op)
            out.paste(im, (round(x + w.width / 2 - im.width / 2), round(a["y"] - im.height / 2 + 30 * (1 - q))), im)
        x += w.width + sp


def make_patches(cfg, im, src, bgc):
    """Перевод надписи прямо в таблице: фон как у страницы, жирный Roboto (Helvetica-подобный) вместо оригинала.
    Кегль подбирается по высоте прописных оригинала; если не влезает в ширину — сжимается (печатает, сколько %)."""
    out = []
    for pt in cfg.get("patches", []):
        x0, y0, x1, y1 = pt["rect"]
        W_, H_ = x1 - x0, y1 - y0
        if pt.get("img"):                                        # готовая картинка перевода (make_insert.py --dump), того же размера, что страница
            full = Image.open(pt["img"]).convert("RGB").resize(im.size, Image.LANCZOS)
            out.append(dict(pt, arr=np.asarray(full.crop((x0, y0, x1, y1)), np.float32))); continue
        ink = np.asarray(im.convert("L").crop((x0, y0, x1, y1)))
        cols = np.nonzero((ink < 110).any(axis=0))[0]; rows = np.nonzero((ink[:, :pt.get("cap_w", 22)] < 110).any(axis=1))[0]
        cap = max(8, rows.max() - rows.min() + 1)               # высота первой прописной оригинала
        fam = {}
        def font(ch, size):
            k = (mi.is_cyr(ch), size)
            if k not in fam:
                fam[k] = ImageFont.truetype(os.path.join(HERE, "fonts", f"roboto-{'cyrillic' if k[0] else 'latin'}-700-normal.woff"), size)
            return fam[k]
        txt = pt["text"]
        size = round(cap / 0.711)                                # у Roboto высота прописной ≈ 0,711 кегля
        def width(sz):
            return sum(font(ch, sz).getlength(ch) for ch in txt)
        natural = size; maxw = (cols.max() - cols.min() + 1) + pt.get("extra_w", 0) if len(cols) else W_ - 8
        while size > 8 and width(size) > maxw:
            size -= 1
        print(f"перевод: кегль {size}/{natural} = {100 * size / natural:.0f}% от оригинала")
        img = Image.new("RGB", (W_, H_), tuple(int(v) for v in bgc)); d = ImageDraw.Draw(img)
        x = cols.min() if len(cols) else 4
        base = rows.max() + 1 if len(rows) else H_ * 0.75
        for ch in txt:
            d.text((x, base), ch, font=font(ch, size), fill=(18, 18, 18), anchor="ls"); x += font(ch, size).getlength(ch)
        out.append(dict(pt, arr=np.asarray(img, np.float32)))
    return out


def build(cfg, bg):
    T = cfg["duration"]
    im = Image.open(cfg["img"]).convert("RGB")
    if cfg.get("pad_bottom"):                               # пустое поле снизу — камере есть куда ехать к накладке
        big = Image.new("RGB", (im.width, im.height + int(cfg["pad_bottom"])), (255, 255, 255)); big.paste(im, (0, 0)); im = big
    src = np.asarray(im, np.float32)
    bgc = np.median(src.reshape(-1, 3), axis=0)
    dimmed = np.asarray(im.filter(ImageFilter.GaussianBlur(max(1.5, im.width / 400))), np.float32) * 0.38 + bgc * 0.62
    # выделения: одно (hl + hl_t, гаснет вся строка целиком) или несколько (marks — по очереди, гаснет всё, кроме них)
    marks = cfg["marks"] if "marks" in cfg else [{"hl": cfg["hl"], "t": cfg["hl_t"], "row": True}]
    keep = np.ones(src.shape[:2], np.float32)                    # статичная часть: переводы и полосы-колонки
    ovs = []
    for ov in cfg.get("overlays", []):                       # накладки: кусок таблицы, которого нет на скрине, ложится поверх
        st = Image.open(ov["img"]).convert("RGB")
        if ov.get("crop"):
            st = st.crop(tuple(ov["crop"]))
        st = st.resize((max(2, round(st.width * ov["scale"])), max(2, round(st.height * ov["scale"]))), Image.LANCZOS)
        arr = np.asarray(st, np.float32)
        darr = np.asarray(st.filter(ImageFilter.GaussianBlur(max(1.5, im.width / 400))), np.float32) * 0.38 + bgc * 0.62
        ovs.append(dict(ov, arr=arr, darr=darr, X0=int(round(ov["x"])), Y0=int(round(ov["y"])), h=arr.shape[0], w=arr.shape[1]))
    stickers = ml.load_stickers(cfg.get("stickers", []))
    # столбики диаграммы растут снизу: на их месте сначала «пустой» участок графика (колонки из src_x, с сеткой)
    bars = []
    for bspec in cfg.get("bars", []):
        x0, y0, x1, y1 = bspec["rect"]; w_ = x1 - x0 + 1
        ext = int(0.12 * (y1 - y0))
        sx = bspec["src_x"]; sw = bspec.get("src_w", 80)
        cols = [sx + (k % sw) for k in range(w_)]
        emp = src[y0 - ext:y1 + 1][:, cols].copy()
        colr = np.median(src[y0 + 5:y1 - 5, x0 + 5:x1 - 5].reshape(-1, 3), axis=0)
        bars.append(dict(bspec, x0=x0, y0=y0, x1=x1, y1=y1, ext=ext, emp=emp, col=colr, orig=src[y0:y1 + 1, x0:x1 + 1].copy()))
    patches = make_patches(cfg, im, src, bgc)
    for pt in patches:                                           # перевод не гасим вместе с остальным — он должен читаться
        x0, y0, x1, y1 = pt["rect"]
        keep[y0:y1, x0:x1] = 0
    bands = cfg.get("bands", [])                               # мягкие полосы-«перекрестье» (строка / колонка)
    for b in bands:
        x0, y0, x1, y1 = b["rect"]
        keep[int(y0) - 4:int(y1) + 4, int(x0) - 4:int(x1) + 4] = 0
    keep_static = keep
    _kcache = {}

    def keep_at(t):
        """Что не гасится: статичная часть + места отмеченных маркеров, но только с момента их появления
        (до этого строка гаснет вместе со всеми — иначе она торчала бы яркой раньше времени)."""
        key = tuple(bool(t >= mk_["t"]) for mk_ in marks)
        if key not in _kcache:
            k = keep_static.copy()
            kp = int(cfg.get("keep_pad", 6))
            for mk_, on in zip(marks, key):
                if not on:
                    continue
                x0, y0, x1, y1 = mk_["hl"]
                if mk_.get("row"):
                    k[int(y0) - kp:int(y1) + kp, :] = 0                 # запас вокруг строки, не гасится
                else:
                    k[int(y0) - kp:int(y1) + kp, int(x0) - 8:int(x1) + 8] = 0
            _kcache[key] = np.asarray(Image.fromarray((k * 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(cfg.get("keep_blur", 4))), np.float32) / 255
        return _kcache[key]
    full = (0.0, 0.0, float(im.width), float(im.height))
    views = cfg.get("views") or [{"t": cfg["zoom_t"], "dur": cfg.get("zoom_dur", M.ZOOMROW), "view": cfg["view"]}]
    view = tuple(float(v) for v in views[0]["view"])
    w0 = cfg["h0"] * im.width / im.height
    cap = caption_layer(cfg, bg) if cfg.get("source") else None
    bwr, radr = M.WIN_BORDER, M.WIN_RADIUS

    def content(t):
        a = src
        dmm = dimmed
        wp = cfg.get("wipe")
        if wp:                                                   # график «рисуется» слева направо: правее фронта — пусто
            q = M.ease((t - wp["t"]) / wp.get("dur", 2.0))
            if q < 1:
                a = src.copy() if a is src else a
                x0, y0, x1, y1 = wp["rect"]
                front = int(x0 + (x1 - x0) * q)
                a[y0:y1, front:x1] = bgc
        if bars:
            a = src.copy() if a is src else a
            for b_ in bars:
                x0, y0, x1, y1, ext = b_["x0"], b_["y0"], b_["x1"], b_["y1"], b_["ext"]
                a[y0 - ext:y1 + 1, x0:x1 + 1] = b_["emp"]
                u = t - b_["t"]
                if u > 0:
                    # по умолчанию без перелёта: плавный рост и мягкая остановка ("overshoot": true — с отскоком)
                    q = M.pop(u, b_.get("dur", 0.7), M.OVERSHOOT_SMALL) if b_.get("overshoot") else M.ease_out(u / b_.get("dur", 0.9))
                    hgt = (y1 + 1 - y0) * q
                    top = int(round(y1 + 1 - hgt))
                    if top <= y1:
                        ya = max(top, y0)
                        a[ya:y1 + 1, x0:x1 + 1] = b_["orig"][ya - y0:]
                        if top < y0:                                 # перелёт выше настоящей высоты — цвет столбика
                            a[max(top, y0 - ext):y0, x0:x1 + 1] = b_["col"]
        for pt in patches:                                       # оригинал → перевод: проявление поверх
            q = M.ease((t - pt["t"]) / M.PATCH)
            if q > 0:
                if a is src:
                    a = src.copy()
                x0, y0, x1, y1 = pt["rect"]
                a[y0:y1, x0:x1] = a[y0:y1, x0:x1] * (1 - q) + pt["arr"] * q
        for ov in ovs:                                           # накладка проявляется поверх с мягкой тенью по краю
            q = M.ease((t - ov["t"]) / ov.get("dur", 0.6))
            if q > 0:
                if a is src:
                    a = src.copy()
                if dmm is dimmed:
                    dmm = dimmed.copy()
                Y0, X0, h, w = ov["Y0"], ov["X0"], ov["h"], ov["w"]
                ya, yb, xa, xb = max(0, Y0 - 16), min(a.shape[0], Y0 + h + 16), max(0, X0 - 16), min(a.shape[1], X0 + w + 16)
                m = np.zeros((yb - ya, xb - xa), np.float32); m[Y0 - ya:Y0 - ya + h, X0 - xa:X0 - xa + w] = 1
                m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5)), np.float32) / 255
                a[ya:yb, xa:xb] *= (1 - 0.22 * q * m)[..., None]
                a[Y0:Y0 + h, X0:X0 + w] = a[Y0:Y0 + h, X0:X0 + w] * (1 - q) + ov["arr"] * q
                dmm[Y0:Y0 + h, X0:X0 + w] = dmm[Y0:Y0 + h, X0:X0 + w] * (1 - q) + ov["darr"] * q
        dm = M.ease((t - cfg["dim_t"]) / M.DIM)
        if any(o.get("dim_t") is not None for o in ovs):          # накладка гаснет в своё время (overlays[i].dim_t), а не вместе со всеми
            dmap = np.full(src.shape[:2], dm, np.float32)
            for o in ovs:
                if o.get("dim_t") is not None:
                    dmap[o["Y0"]:o["Y0"] + o["h"], o["X0"]:o["X0"] + o["w"]] = M.ease((t - o["dim_t"]) / M.DIM)
            if dmap.max() > 0:
                a = a + (dmm - a) * (keep_at(t) * dmap)[..., None]
        elif dm > 0:
            a = a + (dmm - a) * (keep_at(t) * dm)[..., None]
        mb = np.zeros(src.shape[:2], np.float32)
        for b in bands:                                         # полоса проходит вдоль строки или спускается по колонке
            q = M.ease((t - b["t"]) / b.get("dur", M.BAND))
            if q > 0:
                x0, y0, x1, y1 = b["rect"]
                if b.get("dir", "h") == "h":
                    mb[int(y0):int(y1), int(x0):int(math.ceil(x0 + (x1 - x0) * q))] = 1
                else:
                    mb[int(y0):int(math.ceil(y0 + (y1 - y0) * q)), int(x0):int(x1)] = 1
        if mb.any():
            a = a * (1 - mb[..., None] * M.BAND_ALPHA * (1 - HL))
        for mk_ in marks:                                       # жирное начертание цифр: утолщаем штрихи на 1 px вправо
            if mk_.get("bold"):
                q = M.ease((t - mk_["t"]) / cfg.get("hl_dur", M.HIGHLIGHT_INSERT))
                if q > 0:
                    if a is src:
                        a = src.copy()
                    x0, y0, x1, y1 = (int(v) for v in mk_["hl"])
                    reg = a[y0:y1, x0:x1]
                    sh = np.pad(reg[:, :-1], ((0, 0), (1, 0), (0, 0)), mode="edge")
                    a[y0:y1, x0:x1] = reg + (np.minimum(reg, sh) - reg) * q
        m = np.zeros(src.shape[:2], np.float32); ms = np.zeros(src.shape[:2], np.float32)
        for mk_ in marks:                                       # маркер «шторкой» слева направо, каскадом
            mk = M.ease((t - mk_["t"]) / cfg.get("hl_dur", M.HIGHLIGHT_INSERT))
            if mk > 0:
                x0, y0, x1, y1 = mk_["hl"]
                f_off = 1.0 - (M.ease((t - mk_["off"]) / 0.5) if mk_.get("off") is not None else 0.0)   # marks[i].off: маркер гаснет (когда ложится перевод)
                (ms if mk_.get("strong") else m)[int(y0):int(y1), int(x0):int(math.ceil(x0 + (x1 - x0) * mk))] = f_off
        if m.any():
            a = a * (1 - m[..., None] * (1 - HL))
        if ms.any():                                            # главное место — маркер насыщеннее
            a = a * (1 - ms[..., None] * (1 - HL * HL * HL))
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    def frame(t):
        out = bg.copy()
        if cap is not None:
            ca = M.ease_out((t - cfg.get("source_at", 0.5)) / M.CAPTION)
            if ca > 0:
                c = cap[0].copy(); c.putalpha(c.getchannel("A").point(lambda v: int(v * ca)))
                out.paste(c, (0, int(cap[1] + 20 * (1 - ca))), c)
        u = t - cfg.get("t", 0.0)
        if u < 0:
            return out
        # камера: от всей картинки к первому виду, затем (если есть) переезд к следующим видам одной ширины.
        # Масштаб «пиксель картинки → пиксель кадра» меняется по экспоненте — окно не раздувается по пути.
        r = list(full); kk = cfg["h0"] / im.height; z = 0.0
        for i, vw in enumerate(views):
            q = M.ease((t - vw["t"]) / vw.get("dur", M.ZOOMROW))
            if i == 0:
                z = q
            if q <= 0:
                break
            tgt = [float(x) for x in vw["view"]]; kt = cfg["w1"] / (tgt[2] - tgt[0])
            r = [f0 + (v0 - f0) * q for f0, v0 in zip(r, tgt)]
            kk = math.exp(math.log(kk) + (math.log(kt) - math.log(kk)) * q)
            if q < 1:
                break
        ww = (r[2] - r[0]) * kk
        p = M.pop(u, M.WIN_POP, M.OVERSHOOT_SMALL)
        s = (M.WIN_FROM + (1 - M.WIN_FROM) * p) * (1 + M.DRIFT * 0.6 * (t / T))
        ww *= s
        hh = ww * (r[3] - r[1]) / (r[2] - r[0])
        bw = max(2, round(bwr * ww * (1 - 0.4 * z))); rad = round(radr * ww * (1 - 0.4 * z))
        cw, ch = max(2, round(ww - 2 * bw)), max(2, round(hh - 2 * bw))
        piece = content(t).crop(tuple(int(round(v)) for v in r)).resize((cw, ch), Image.LANCZOS)
        sw_, sh_ = cw + 2 * bw, ch + 2 * bw
        outer = Image.new("L", (sw_, sh_), 0); ImageDraw.Draw(outer).rounded_rectangle([0, 0, sw_ - 1, sh_ - 1], rad + bw, fill=255)
        inner = Image.new("L", (cw, ch), 0); ImageDraw.Draw(inner).rounded_rectangle([0, 0, cw - 1, ch - 1], rad, fill=255)
        card = Image.new("RGBA", (sw_, sh_), (255, 255, 255, 0))
        card.paste((255, 255, 255, 255), (0, 0), outer)
        card.paste(piece, (bw, bw), inner)
        op = M.ease_out(u / M.APPEAR)
        if op < 1:
            card.putalpha(card.getchannel("A").point(lambda v: int(v * op)))
        cx, cy = cfg["at"]
        if cfg.get("at1"):                                      # окно уезжает на новое место вместе с приближением
            cx += (cfg["at1"][0] - cx) * z; cy += (cfg["at1"][1] - cy) * z
        cy += 40 * (1 - p)
        # мягкая тень: размываем маленькую маску и растягиваем (быстро даже на 4K)
        k = 8; pad = int(0.08 * sw_)
        sm = Image.new("L", ((sw_ + 2 * pad) // k, (sh_ + 2 * pad) // k), 0)
        ImageDraw.Draw(sm).rounded_rectangle([pad // k, pad // k, (pad + sw_) // k, (pad + sh_) // k], (rad + bw) // k, fill=int(150 * op))
        sm = sm.filter(ImageFilter.GaussianBlur(0.03 * sw_ / k)).resize((sw_ + 2 * pad, sh_ + 2 * pad), Image.BILINEAR)
        lift = 1 - M.ease_out(u / M.STICKER_LAND)
        out.paste((0, 0, 0), (round(cx - sm.width / 2), round(cy - sm.height / 2 + (0.015 + 0.04 * lift) * sh_)), sm)
        out.paste(card, (round(cx - sw_ / 2), round(cy - sh_ / 2)), card)
        if stickers:                                             # наклейки поверх сцены: шлепок, доворот, лёгкое покачивание
            ml.draw_stickers(out, stickers, t)
        if cfg.get("compare"):
            draw_compare(out, cfg["compare"], t)
        if cfg.get("fly"):                                       # цифры вылетают из ячеек вниз, в строку сравнения
            kx = cw / (r[2] - r[0]); ox = cx - sw_ / 2 + bw; oy = cy - sh_ / 2 + bw
            to_screen = lambda x0, y0, x1, y1: (ox + (x0 - r[0]) * kx, oy + (y0 - r[1]) * kx,
                                                ox + (x1 - r[0]) * kx, oy + (y1 - r[1]) * kx)
            draw_fly(out, cfg["fly"], t, to_screen)
        co = cfg.get("callout")
        if co and t >= co["t"]:                                  # выноска под окном с линией от ячейки
            sx, sy = co["at"]
            kx = cw / (r[2] - r[0])
            px = cx - sw_ / 2 + bw + (sx - r[0]) * kx
            py = cy - sh_ / 2 + bw + (sy - r[1]) * kx
            draw_callout(out, co, t - co["t"], px, py, cy + sh_ / 2)
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
        for i, t in enumerate(cfg.get("preview_at") or [0.4, 1.2, 1.8, T - 0.05]):
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
