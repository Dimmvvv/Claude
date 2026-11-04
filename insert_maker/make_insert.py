#!/usr/bin/env python3
"""
Видео-вставка «скриншот статьи на фоне»: карточка появляется, предложение
выделяется маркером, остальной текст гаснет, предложение заменяется переводом.

Шаг 1 — найти строки и слова на скриншоте (без OCR, по пикселям):
    python3 make_insert.py shot.png --detect
    -> shot_detect.png с номерами строк и слов

Шаг 2 — собрать видео:
    python3 make_insert.py shot.png --sel 7:9-9:-1 \
        --ru "В октябре *Adweek* сообщил, ..." \
        --source "The Hollywood Reporter, «...»" --out out.mp4

  --sel  СТРОКА:СЛОВО-СТРОКА:СЛОВО (с 1; -1 = последнее слово строки)
  --ru   перевод; *так* = курсив
  --preview  быстрые PNG-кадры вместо видео
"""
import argparse, os, sys, subprocess, re
from functools import lru_cache
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
W, H = 3840, 2160

HL_COLOR = np.array([206, 195, 244], np.float32)   # фиолетовый маркер из референса
CAPTION_LABEL = (114, 119, 143)
CAPTION_TEXT = (178, 181, 206)
INTER = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"
INTER_LIGHT = "/usr/share/fonts/opentype/inter/Inter-Light.otf"


# ---------------------------------------------------------------- detection
def detect_layout(img):
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    # фон = самый частый цвет (медиана ломается, если на скриншоте большое фото)
    smp = a.reshape(-1, 3)[:: max(1, a.size // 300000)] // 4
    vals, cnt = np.unique(smp, axis=0, return_counts=True)
    bg = vals[np.argmax(cnt)] * 4 + 2
    ink = np.abs(a - bg).max(2) > 70
    # рамки скриншота (линия на всю высоту/ширину) — не текст
    ink[:, ink.mean(0) > 0.8] = False
    ink[ink.mean(1) > 0.8, :] = False
    rows = ink.sum(1)
    runs, s = [], None
    for y, v in enumerate(rows > 0):
        if v and s is None:
            s = y
        if not v and s is not None:
            runs.append([s, y]); s = None
    if s is not None:
        runs.append([s, len(rows)])
    if not runs:
        sys.exit("Текст не найден")
    hmed = np.median([r[1] - r[0] for r in runs])
    # склеиваем мелкие куски (точки над i, подчёркивания) и выкидываем линии-рамки
    merged = []
    for r in runs:
        if merged and (r[1] - r[0] < 0.45 * hmed) and r[0] - merged[-1][1] < 0.3 * hmed:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    lines = []
    for y0, y1 in merged:
        if y1 - y0 < 0.45 * hmed:
            continue
        band = ink[y0:y1]
        cols = band.sum(0) > 0
        h = y1 - y0
        gap_min = max(3, 0.19 * h)
        words, s, last = [], None, None
        xs = np.where(cols)[0]
        for x in xs:
            if s is None:
                s = last = x
            elif x - last > gap_min:
                words.append([s, last + 1]); s = x
            last = x
        if s is not None:
            words.append([s, last + 1])
        prof = band.sum(1).astype(float)
        lower = np.arange(len(prof)) > len(prof) * 0.45
        drop = np.where(lower[:-1], prof[:-1] - prof[1:], -1)
        baseline = y0 + int(np.argmax(drop)) + 1
        lines.append(dict(y0=y0, y1=y1, base=baseline, words=words))
    hs = [l["y1"] - l["y0"] for l in lines]
    info = dict(lines=lines, bg=tuple(int(v) for v in bg), hmed=float(np.median(hs)),
                left=min(l["words"][0][0] for l in lines),
                right=max(l["words"][-1][1] for l in lines))
    # высота строчных букв (база - верх x-height) для подбора кегля
    asc = [l["base"] - l["y0"] for l in lines]
    info["asc"] = float(np.median(asc))
    # цвет текста
    dark = a[ink & (a.sum(2) < np.median(a[ink].sum(1)))]
    info["ink"] = tuple(int(v) for v in np.median(dark, 0)) if len(dark) else (20, 20, 20)
    return info


def draw_detect(img, info, path):
    k = 2
    im = img.convert("RGB").resize((img.width * k, img.height * k), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(INTER, 16)
    fl = ImageFont.truetype(INTER, 22)
    for li, l in enumerate(info["lines"], 1):
        d.text((4, l["y0"] * k), f"L{li}", fill=(220, 0, 0), font=fl)
        for wi, (x0, x1) in enumerate(l["words"], 1):
            d.rectangle([x0 * k, l["y0"] * k, x1 * k, l["y1"] * k], outline=(0, 120, 255))
            d.text((x0 * k + 1, l["y1"] * k), str(wi), fill=(0, 140, 0), font=f)
        d.line([0, l["base"] * k, 30, l["base"] * k], fill=(255, 0, 255), width=2)
    im.save(path)


# ---------------------------------------------------------------- text layout
FONT_STYLE = "serif"
SANS = {"sans": ("Inter-Regular.otf", "Inter-Italic.otf"),
        "sans-bold": ("InterDisplay-Bold.otf", "InterDisplay-BoldItalic.otf")}


def load_fonts(size):
    if FONT_STYLE in SANS:
        d = "/usr/share/fonts/opentype/inter/"
        r = ImageFont.truetype(d + SANS[FONT_STYLE][0], size)
        i = ImageFont.truetype(d + SANS[FONT_STYLE][1], size)
        return {("cyr", False): r, ("lat", False): r, ("cyr", True): i, ("lat", True): i}
    def f(n):
        return ImageFont.truetype(os.path.join(FONTS, f"source-serif-4-{n}.woff"), size)
    return {("cyr", False): f("cyrillic-400-normal"), ("lat", False): f("latin-400-normal"),
            ("cyr", True): f("cyrillic-400-italic"), ("lat", True): f("latin-400-italic")}


def is_cyr(ch):
    o = ord(ch)
    return 0x0400 <= o <= 0x052F or o == 0x2116


def tokenize(text):
    """-> слова, каждое = список (символ, italic)"""
    out, ital = [], False
    word = []
    for ch in text:
        if ch == "*":
            ital = not ital; continue
        if ch == " ":
            if word:
                out.append(word); word = []
            continue
        word.append((ch, ital))
    if word:
        out.append(word)
    return out


def runs_of(word):
    runs = []
    for ch, it in word:
        key = ("cyr" if is_cyr(ch) else "lat", it)
        if runs and runs[-1][0] == key:
            runs[-1][1] += ch
        else:
            runs.append([key, ch])
    return runs


def word_len(word, fonts):
    return sum(fonts[k].getlength(t) for k, t in runs_of(word))


def layout(words, fonts, slots):
    """slots: [(x0, xmax)] на строку. -> список строк [(x, word)] или None"""
    space = fonts[("cyr", False)].getlength(" ")
    res, i = [], 0
    for (x0, xmax) in slots:
        x, line = x0, []
        while i < len(words):
            wl = word_len(words[i], fonts)
            if x + wl > xmax and line:
                break
            if x + wl > xmax:
                return None
            line.append((x, words[i])); x += wl + space; i += 1
        res.append(line)
    return res if i == len(words) else None


# ---------------------------------------------------------------- build static layers
def ease(t):  # easeInOutCubic
    t = min(max(t, 0.0), 1.0)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_out_back(t, c=1.7):
    t = min(max(t, 0.0), 1.0)
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def parse_sel(sel, lines):
    m = re.fullmatch(r"(\d+):(-?\d+)-(\d+):(-?\d+)", sel.strip())
    if not m:
        sys.exit("--sel формат: 7:9-9:-1")
    l0, w0, l1, w1 = map(int, m.groups())
    def wi(l, w):
        n = len(lines[l - 1]["words"])
        return n + w if w < 0 else w - 1
    return l0 - 1, wi(l0, w0), l1 - 1, wi(l1, w1)


def build(args):
    shot = Image.open(args.image).convert("RGB")
    info = detect_layout(shot)
    lines = info["lines"]
    sels = args.sel if isinstance(args.sel, list) else [args.sel]
    rus = args.ru if isinstance(args.ru, list) else [args.ru]
    if len(sels) != len(rus):
        sys.exit("Число --sel и --ru должно совпадать: по паре на каждое выделение")
    parsed = [parse_sel(s, lines) for s in sels]
    no_ru = all(not r.strip() for r in rus)        # --ru '' → только выделение, без замены на перевод

    # размер карточки в финале
    max_w, max_h = W * args.card_w, H * 0.66
    K = min(max_w / shot.width, max_h / shot.height)
    cw, ch = round(shot.width * K), round(shot.height * K)
    A = shot.resize((cw, ch), Image.LANCZOS)
    global FONT_STYLE
    FONT_STYLE = args.font
    probe = load_fonts(200)
    asc_box = probe[("lat", False)].getbbox("dlfhk", anchor="ls")
    cap_h = -asc_box[1] / 200

    # прямоугольники выделения (в координатах скриншота) и «слоты» для перевода;
    # размеры берём по самим выделенным строкам (заголовок крупнее текста)
    hl_rects, slots_all, words_all, size0s, sel_m = [], [], [], [], []
    for (L0, W0, L1, W1), ru in zip(parsed, rus):
        sl = lines[L0:L1 + 1]
        asc_s = float(np.median([l["base"] - l["y0"] for l in sl]))
        h_s = float(np.median([l["y1"] - l["y0"] for l in sl]))
        pad_s = 0.10 * h_s
        left_s = min(l["words"][0][0] for l in sl[1:]) if len(sl) > 1 else sl[0]["words"][0][0]
        col = [l for l in lines if abs(l["words"][0][0] - left_s) < 0.6 * h_s]
        right_s = max(l["words"][-1][1] for l in (col or sl))
        # не дальше, чем доходил сам выделенный текст (+ полстроки запаса)
        right_s = min(right_s, max(l["words"][-1][1] for l in sl) + 0.5 * h_s)
        sel_m.append((h_s, pad_s))
        rects = []
        for li in range(L0, L1 + 1):
            l = lines[li]
            ws = l["words"]
            xa = ws[W0][0] if li == L0 else ws[0][0]
            xb = ws[W1][1] if li == L1 else ws[-1][1]
            top = l["base"] - asc_s - 0.12 * h_s
            bot = l["base"] + 0.34 * h_s
            rects.append([xa - pad_s, top, xb + pad_s, bot])
        hl_rects += rects
        tail_after = W1 < len(lines[L1]["words"]) - 1
        slots = []
        for i, li in enumerate(range(L0, L1 + 1)):
            x0 = rects[i][0] + pad_s if i == 0 else left_s
            xmax = (lines[L1]["words"][W1][1] if (li == L1 and tail_after) else right_s)
            slots.append((x0 * K, xmax * K + 2))
        slots_all.append(slots)
        words_all.append(tokenize(ru))
        size0s.append(asc_s * K / cap_h)

    # кегль: как у оригинала, уменьшаем (одинаково для всех выделений), пока всё не влезет
    def fit(words, slots, s0):
        sz = s0
        while sz > s0 * 0.6:
            if layout(words, load_fonts(round(sz)), slots):
                return sz / s0
            sz *= 0.97
        return None
    ratios = [fit(w, sl, s0) for w, sl, s0 in zip(words_all, slots_all, size0s)]
    if None in ratios:
        sys.exit("Перевод не помещается в строки выделения — сократите текст")
    ratio = min(ratios)
    while True:
        fonts_all = [load_fonts(round(s0 * ratio)) for s0 in size0s]
        lays = [layout(w, f, sl) for w, f, sl in zip(words_all, fonts_all, slots_all)]
        if all(lays):
            break
        ratio *= 0.98
    if ratio < 0.97:
        print(f"! перевод уменьшен до {ratio:.0%} от кегля оригинала, чтобы влезть")

    # слой с переводом R и области замены
    R = A.copy()
    dr = ImageDraw.Draw(R)
    ink = info["ink"]
    ru_rects = []
    hi = 0
    for (L0, W0, L1, W1), lay, fonts, (h_s, pad_s) in zip(parsed, lays, fonts_all, sel_m):
        for i, li in enumerate(range(L0, L1 + 1)):
            r = hl_rects[hi]; hi += 1
            end_ru = (lay[i][-1][0] + word_len(lay[i][-1][1], fonts)) if lay[i] else 0
            x1 = max(r[2] * K, end_ru + pad_s * K)
            # края — до границ строки, чтобы закрыть подчёркивания ссылок и надстрочные знаки (11th)
            rect = [r[0] * K, min(r[1], lines[li]["y0"] - 0.04 * h_s) * K, x1, max(r[3], lines[li]["y1"] + 0.04 * h_s) * K]
            ru_rects.append(rect)
            dr.rectangle(rect, fill=info["bg"])
    for (L0, W0, L1, W1), lay, fonts in zip(parsed, lays, fonts_all):
        for i, li in enumerate(range(L0, L1 + 1)):
            base = lines[li]["base"] * K
            for x, w in lay[i]:
                for key, t in runs_of(w):
                    dr.text((x, base), t, font=fonts[key], fill=ink, anchor="ls")
                    x += fonts[key].getlength(t)
    Rn = np.asarray(R, np.float32)
    An = np.asarray(A, np.float32)

    # тусклый слой: размытие + осветление
    B = A.filter(ImageFilter.GaussianBlur(args.blur * K))
    Bn = np.asarray(B, np.float32) * (1 - args.dim) + np.array(info["bg"], np.float32) * args.dim

    keep = Image.new("L", (cw, ch), 0)
    kd = ImageDraw.Draw(keep)
    for r in ru_rects:
        kd.rectangle([r[0] - 4, r[1] - 4, r[2] + 4, r[3] + 4], fill=255)
    keep = np.asarray(keep.filter(ImageFilter.GaussianBlur(3 * K)), np.float32)[..., None] / 255

    # «пути» для чтения слева направо по строкам
    def path(rects, scale):
        segs, tot = [], 0.0
        for r in rects:
            x0, y0, x1, y1 = [v * scale for v in r]
            segs.append((x0, x1, int(y0), int(y1), tot)); tot += x1 - x0
        return segs, tot
    hl_path = path(hl_rects, K)
    ru_path = path(ru_rects, 1)

    xs = np.arange(cw, dtype=np.float32)[None, :]

    def sweep_mask(pth, p, feather):
        segs, tot = pth
        m = np.zeros((ch, cw), np.float32)
        dist = p * (tot + feather * len(segs))
        for j, (x0, x1, y0, y1, off) in enumerate(segs):
            front = x0 + dist - off - feather * j
            v = np.clip((front - xs) / feather + 0.5, 0, 1)
            v = v * ((xs >= x0 - 1) & (xs <= x1 + 1))
            m[max(0, y0):y1] = np.maximum(m[max(0, y0):y1], v)
        return m

    # округлённые углы/тень
    rad = int(0.012 * cw)
    alpha = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(alpha).rounded_rectangle([0, 0, cw - 1, ch - 1], rad, fill=255)
    sh_pad = int(0.08 * cw)
    shadow = Image.new("L", (cw + 2 * sh_pad, ch + 2 * sh_pad), 0)
    ImageDraw.Draw(shadow).rounded_rectangle([sh_pad, sh_pad + 0.02 * ch, sh_pad + cw, sh_pad + ch + 0.02 * ch], rad, fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(0.025 * cw))

    sticker = args.intro == "sticker"
    if sticker:
        bw = int(0.022 * cw)                       # белая кайма наклейки
        sw_, sh_ = cw + 2 * bw, ch + 2 * bw
        st_alpha = Image.new("L", (sw_, sh_), 0)
        ImageDraw.Draw(st_alpha).rounded_rectangle([0, 0, sw_ - 1, sh_ - 1], rad + bw, fill=255)
        sp = int(0.07 * cw)
        st_shadow = Image.new("L", (sw_ + 2 * sp, sh_ + 2 * sp), 0)
        ImageDraw.Draw(st_shadow).rounded_rectangle([sp, sp, sp + sw_, sp + sh_], rad + bw, fill=165)
        st_shadow = st_shadow.filter(ImageFilter.GaussianBlur(0.02 * cw))

    T = args.duration
    t_hl = (1.0, 1.0 + args.hl_time)
    t_dim = (t_hl[0] + 0.5, t_hl[0] + 1.1)
    t_ru = (t_hl[1] + args.pause, t_hl[1] + args.pause + args.ru_time)

    def card_state(t):
        q = lambda v: round(v, 3)
        return (q(ease((t - t_dim[0]) / (t_dim[1] - t_dim[0]))),
                q(ease((t - t_hl[0]) / (t_hl[1] - t_hl[0]))),
                0.0 if no_ru else q(ease((t - t_ru[0]) / (t_ru[1] - t_ru[0]))))

    @lru_cache(maxsize=4)
    def card_img(dim, hp, rp):
        img = An
        if dim > 0:
            img = img + (Bn - img) * (dim * (1 - keep))
        if hp > 0:
            m = sweep_mask(hl_path, hp, 6 * K)[..., None]
            img = img * (1 - m * (1 - HL_COLOR / 255))
        if rp > 0:
            m = sweep_mask(ru_path, rp, 14 * K)[..., None]
            img = img + (Rn - img) * m
        return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))

    # фон и подпись
    bg = Image.open(args.bg).convert("RGB")
    if bg.size != (W, H):
        bg = bg.resize((W, H), Image.LANCZOS)
    cap_layer = None
    if args.source:
        cap_layer = Image.new("RGBA", (W, 200), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cap_layer)
        fl = ImageFont.truetype(INTER, 34)
        x = 338
        for chh in "ИСТОЧНИК":
            cd.text((x, 100), chh, font=fl, fill=CAPTION_LABEL, anchor="lm")
            x += fl.getlength(chh) + 6
        x += 28
        cd.line([x, 70, x, 130], fill=(60, 64, 96), width=2)
        x += 32
        cd.text((x, 100), args.source, font=ImageFont.truetype(INTER, 44), fill=CAPTION_TEXT, anchor="lm")
    t_cap = t_dim

    def frame_sticker(t, img, out):
        # «шлепок»: масштаб с перелётом, поворот доводится до лёгкого наклона,
        # тень сначала «приподнята», потом прилипает
        pop = ease_out_back(t / 0.5)
        s = (0.95 + 0.05 * (t / T)) * (0.4 + 0.6 * pop)
        ang = -10 * (1 - ease_out(t / 0.6))      # доворачивается до ровного положения
        op = ease_out(t / 0.1)
        lift = 1 - ease_out(t / 0.55)
        cx, cy = W / 2, H * (0.52 - 0.02 * (t / T))
        st = Image.new("RGBA", (sw_, sh_), (255, 255, 255, 0))
        st.paste((255, 255, 255, 255), (0, 0), st_alpha)
        st.paste(img, (bw, bw), alpha)
        w2, h2 = max(2, round(sw_ * s)), max(2, round(sh_ * s))
        st = st.resize((w2, h2), Image.LANCZOS).rotate(ang, Image.BICUBIC, expand=True)
        if op < 1:
            st.putalpha(st.getchannel("A").point(lambda v: int(v * op)))
        ss = s * (1 + 0.08 * lift)
        shd = st_shadow.resize((max(2, round(st_shadow.width * ss)), max(2, round(st_shadow.height * ss))),
                               Image.BILINEAR).rotate(ang, Image.BILINEAR, expand=True)
        shd = shd.point(lambda v: int(v * op * (0.75 + 0.25 * (1 - lift))))
        dy = (0.012 + 0.05 * lift) * h2
        out.paste((0, 0, 0), (round(cx - shd.width / 2), round(cy - shd.height / 2 + dy)), shd)
        out.paste(st, (round(cx - st.width / 2), round(cy - st.height / 2)), st)
        return out

    # листание внутри карточки: длинная страница той же ширины, что и окно (картинка)
    scroll = None
    if getattr(args, "scroll_page", None):
        sp = Image.open(args.scroll_page).convert("RGB")
        if sp.width != shot.width:
            sys.exit("--scroll-page должна быть той же ширины, что и картинка-окно")
        scroll = (sp, args.scroll_from, args.scroll_y, (0.5, 0.5 + args.scroll_time))
    shift = (scroll[3][1] + 0.15 - t_hl[0]) if scroll else 0.0

    def card_at(t):
        if scroll and t < scroll[3][1]:
            sp, y0, y1, (a, b) = scroll
            p = ease((t - a) / (b - a)); pp = ease((t - 1 / args.fps - a) / (b - a))
            y = y0 + (y1 - y0) * p
            img = sp.resize((cw, ch), Image.LANCZOS, box=(0, y, sp.width, y + shot.height))
            v = abs(p - pp) * abs(y1 - y0) * K            # сдвиг за кадр, пикс. карточки
            if v > 3:                                     # размытие движения
                f = min(v / 3, 30)
                img = img.resize((cw, max(1, int(ch / f))), Image.BILINEAR).resize((cw, ch), Image.BILINEAR)
            return img
        return card_img(*card_state(t - shift))

    def frame(t):
        img = card_at(t)
        intro = ease_out(t / 0.8)
        s = 0.90 + 0.05 * intro + 0.05 * (t / T)
        op = ease_out(t / 0.55)
        w2, h2 = round(cw * s), round(ch * s)
        cx = W / 2
        cy = H * (0.545 - 0.025 * intro - 0.02 * (t / T))
        x0, y0 = round(cx - w2 / 2), round(cy - h2 / 2)
        out = bg.copy()
        if cap_layer is not None:
            ca = ease_out((t - t_cap[0]) / 0.6)
            if ca > 0:
                lay_ = cap_layer.copy()
                lay_.putalpha(lay_.getchannel("A").point(lambda v: int(v * ca)))
                out.paste(lay_, (0, int(1917 + 20 * (1 - ca))), lay_)
        if sticker:
            return frame_sticker(t, img, out)
        sw = round((cw + 2 * sh_pad) * s), round((ch + 2 * sh_pad) * s)
        shm = shadow.resize(sw, Image.BILINEAR).point(lambda v: int(v * op))
        out.paste((0, 0, 0), (round(cx - sw[0] / 2), round(cy - sw[1] / 2)), shm)
        cimg = img.resize((w2, h2), Image.LANCZOS)
        am = alpha.resize((w2, h2), Image.BILINEAR).point(lambda v: int(v * op))
        out.paste(cimg, (x0, y0), am)
        return out

    return frame, info, dict(t_hl=t_hl, t_ru=t_ru, ratio=ratio, shift=shift)


# ---------------------------------------------------------------- render
_FRAME = None


def _init(args):
    global _FRAME
    _FRAME = build(args)[0]


def _render(t):
    return _FRAME(t).tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--sel", action="append")
    ap.add_argument("--ru", action="append")
    ap.add_argument("--source", default="")
    ap.add_argument("--bg", default=os.path.join(HERE, "assets", "bg_4k.png"))
    ap.add_argument("--out")
    ap.add_argument("--duration", type=float, default=7.0)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--card-w", type=float, default=0.62)
    ap.add_argument("--hl-time", type=float, default=0.9)
    ap.add_argument("--pause", type=float, default=0.9)
    ap.add_argument("--ru-time", type=float, default=1.2)
    ap.add_argument("--dim", type=float, default=0.62)
    ap.add_argument("--blur", type=float, default=1.3)
    ap.add_argument("--font", choices=["serif", "sans", "sans-bold"], default="serif",
                    help="шрифт перевода: serif (текст с засечками), sans, sans-bold (заголовки)")
    ap.add_argument("--intro", choices=["fade", "sticker"], default="fade",
                    help="появление карточки: fade (как в референсе) или sticker (наклейка)")
    ap.add_argument("--scroll-page", help="длинная страница той же ширины: перед выделением карточка листается по ней")
    ap.add_argument("--scroll-from", type=float, default=0, help="откуда листать (y верха окна на странице)")
    ap.add_argument("--scroll-y", type=float, help="где остановиться (y верха окна = картинки на странице)")
    ap.add_argument("--scroll-time", type=float, default=1.7)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    args = ap.parse_args()
    stem = os.path.splitext(args.image)[0]

    if args.detect:
        info = detect_layout(Image.open(args.image))
        p = stem + "_detect.png"
        draw_detect(Image.open(args.image), info, p)
        for i, l in enumerate(info["lines"], 1):
            print(f"L{i}: {len(l['words'])} слов")
        print("->", p)
        return
    if not (args.sel and args.ru):
        sys.exit("нужны --sel и --ru (или --detect)")

    frame, info, meta = build(args)
    if args.preview:
        sh = meta.get("shift", 0.0)
        ts = [0.2, meta["t_hl"][0] + 0.45 + sh, meta["t_hl"][1] + 0.4 + sh,
              (meta["t_ru"][0] + meta["t_ru"][1]) / 2 + sh, args.duration - 0.02]
        if sh:
            ts[0] = 0.5 + args.scroll_time * 0.5          # середина листания
        for i, t in enumerate(ts):
            p = f"{stem}_preview_{i}.png"
            frame(t).resize((1920, 1080), Image.LANCZOS).save(p)
            print("->", p, f"t={t:.2f}")
        return

    out = args.out or stem + "_insert.mp4"
    n = int(round(args.duration * args.fps))
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "16",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    from multiprocessing import Pool
    with Pool(args.workers, initializer=_init, initargs=(args,)) as pool:
        for i, buf in enumerate(pool.imap(_render, [k / args.fps for k in range(n)], chunksize=8)):
            ff.stdin.write(buf)
            if i % 60 == 0:
                print(f"\r{i}/{n}", end="", flush=True)
    ff.stdin.close(); ff.wait()
    print(f"\r{n}/{n} -> {out}")


if __name__ == "__main__":
    main()
