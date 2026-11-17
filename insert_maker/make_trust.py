#!/usr/bin/env python3
"""
«Трастовый фонд» на фоне вставок: поляроид ребёнка → пунктир к купюре («для …») →
пунктирная рамка вокруг купюры («лежат отдельно») → поляроид взрослого, пунктир к купюре, на купюре
защёлкивается замок («распоряжается взрослый») → внизу шкала «пока ребёнок не вырастет»
доходит до конца, и замок открывается.

    python3 make_trust.py scene.json [--preview]
Все времена и подписи — в scene.json (см. work/trust/scene.json).
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_levels as ml  # noqa: E402
import make_collage as mc  # noqa: E402
import make_taxcredit as mt  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
CREAM, YEL = ml.CREAM, ml.HL_YELLOW


def st_text(txt, size, col):
    return ml.text_sprite(txt.upper(), lambda sz, ch: ml.st_font(sz, ch), size, col, sp=0.04, lining=True)


def body_text(txt, size, col=CREAM):
    return ml.text_sprite(txt, lambda sz, ch: ml.body_font(sz), size, col)


def dashed(d, pts, q, col, width=10, dash=46, gap=30):
    """Пунктир по ломаной pts, нарисован на долю q длины."""
    segs = list(zip(pts[:-1], pts[1:]))
    total = sum(math.dist(a, b) for a, b in segs)
    left = total * q; pos = 0.0
    for a, b in segs:
        L = math.dist(a, b)
        if left <= 0:
            break
        run = min(L, left)
        k = 0.0
        while k < run:
            ph = (pos + k) % (dash + gap)
            if ph < dash:
                e = min(run, k + (dash - ph))
                p0 = (a[0] + (b[0] - a[0]) * k / L, a[1] + (b[1] - a[1]) * k / L)
                p1 = (a[0] + (b[0] - a[0]) * e / L, a[1] + (b[1] - a[1]) * e / L)
                d.line([p0, p1], fill=col, width=width)
                k = e
            else:
                k += dash + gap - ph
        pos += L; left -= L


def lock_img(size, open_q):
    """Замок: корпус светло-жёлтый, скважина тёмная; дужка поднимается и поворачивается при open_q → 1."""
    ss = 3; S = size * ss
    im = Image.new("RGBA", (S, int(S * 1.6)), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    bw, bh = S * 0.86, S * 0.66
    bx0 = (S - bw) / 2; by0 = S * 1.6 - bh - S * 0.04
    lift = S * 0.28 * open_q
    sw = S * 0.13; r = S * 0.30
    cx = S / 2 + S * 0.0
    # дужка: две ножки и дуга; при открытии правая ножка выходит из корпуса
    top = by0 - S * 0.42 - lift
    col = (60, 40, 30, 255)
    metal = (222, 214, 198, 255)                       # дужка светлая, иначе теряется на тёмно-красном фоне
    for c_, w_ in ((col, sw * 1.45), (metal, sw * 0.8)):
        d.arc([cx - r, top, cx + r, top + 2 * r], 180, 360, fill=c_, width=int(w_))
        d.line([cx - r + sw / 2, top + r, cx - r + sw / 2, by0 + S * 0.05], fill=c_, width=int(w_))
        d.line([cx + r - sw / 2, top + r, cx + r - sw / 2, by0 + S * 0.05 - lift * 1.6], fill=c_, width=int(w_))
    d.rounded_rectangle([bx0, by0, bx0 + bw, by0 + bh], radius=S * 0.1, fill=YEL + (255,), outline=col, width=int(S * 0.05))
    kx, ky = S / 2, by0 + bh * 0.45
    d.ellipse([kx - S * 0.07, ky - S * 0.07, kx + S * 0.07, ky + S * 0.07], fill=col)
    d.polygon([(kx - S * 0.035, ky), (kx + S * 0.035, ky), (kx + S * 0.05, ky + S * 0.18), (kx - S * 0.05, ky + S * 0.18)], fill=col)
    return im.resize((size, int(size * 1.6)), Image.LANCZOS)


def build(cfg, bg):
    T = cfg["duration"]
    child, ccard, _ = mt.polaroid(cfg["child"], 5, lights=False)
    adult, acard, _ = mt.polaroid(cfg["adult"], 9, lights=False)
    shc, sha = mt.soft_shadow(ccard), mt.soft_shadow(acard)
    bs = cfg["bill"]
    bill = Image.open(bs["img"]).convert("RGBA")
    k = bs["w"] / bill.width
    bill = bill.resize((round(bill.width * k), round(bill.height * k)), Image.LANCZOS)
    shb = mt.soft_shadow(bill)
    L = cfg["labels"]
    lab_for = st_text(L["for"]["text"], 120, YEL) if L.get("for", {}).get("text") else None
    lab_sep = st_text(L["separate"]["text"], 110, YEL)
    lab_adult = body_text(L["adult"]["text"], 76)
    lab_grow = body_text(L["grow"]["text"], L["grow"].get("size", 76))
    bx, by = bs["at"]; bw2, bh2 = bill.width / 2, bill.height / 2

    def card(out, spec, im, sh, t):
        u = t - spec["t"]
        if u < 0:
            return
        p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
        s = M.WIN_FROM + (1 - M.WIN_FROM) * p
        ang = spec.get("rot", 0) + (10 if spec.get("rot", 0) < 0 else -10) * (1 - M.ease_out(u / M.STICKER_TURN))
        ang += M.FACE_SWAY * 0.8 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + spec["at"][0])
        mt.place(out, im, sh, spec["at"][0], spec["at"][1], s, ang, M.ease_out(u / M.APPEAR), 1 - M.ease_out(u / M.STICKER_LAND))

    def label(out, im, x, y, t0, t, center=True):
        u = t - t0
        if u <= 0:
            return
        q = M.pop(u, M.WORD_IN, M.OVERSHOOT_SMALL); op = M.ease_out(u / 0.25)
        im = ml.fade(im, op)
        out.paste(im, (round(x - (im.width / 2 if center else 0)), round(y - im.height / 2 + 30 * (1 - q))), im)

    def frame(t):
        out = bg.copy()
        d = ImageDraw.Draw(out, "RGBA")
        lines = cfg["lines"]
        # пунктир от ребёнка и от взрослого к купюре (под карточками)
        for key in ("child", "adult"):
            ln = lines[key]
            q = M.ease((t - ln["t"]) / 0.6)
            if q > 0:
                dashed(d, ln["pts"], q, CREAM + (220,))
        # рамка «отдельно» вокруг купюры
        bxs = cfg["box"]
        q = M.ease((t - bxs["t"]) / 0.9)
        if q > 0:
            x0, y0, x1, y1 = bxs["rect"]
            dashed(d, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], q, YEL + (235,), width=9)
        card(out, cfg["child"], ccard, shc, t)
        card(out, cfg["adult"], acard, sha, t)
        # купюра: шлепок, лёгкое покачивание, «вдох» в конце, когда замок открылся
        u = t - bs["t"]
        if u >= 0:
            p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
            s = 1 + M.LEVEL_SLAP * (1 - p)
            pu = t - cfg["lock"]["open"] - 0.25
            if 0 < pu < 0.45:
                s *= 1 + 0.06 * math.sin(math.pi * pu / 0.45)
            ang = bs.get("rot", 0) - 8 * (1 - M.ease_out(u / M.STICKER_TURN)) + 0.6 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD)
            mt.place(out, bill, shb, bx, by, s, ang, M.ease_out(u / M.APPEAR), 1 - M.ease_out(u / M.STICKER_LAND))
        # замок на углу купюры
        lk = cfg["lock"]; u = t - lk["t"]
        if u >= 0:
            oq = M.ease((t - lk["open"]) / 0.5)
            li = lock_img(lk["size"], oq)
            p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
            sc = 1.6 - 0.6 * p
            li = li.resize((max(2, round(li.width * sc)), max(2, round(li.height * sc))), Image.BILINEAR)
            li = li.rotate(lk.get("rot", 8), Image.BICUBIC, expand=True)
            li = ml.fade(li, M.ease_out(u / 0.15))
            out.paste(li, (round(lk["at"][0] - li.width / 2), round(lk["at"][1] - li.height / 2)), li)
        # шкала «пока ребёнок не вырастет»
        tl = cfg["timeline"]
        u = t - tl["t"]
        if u > 0 and tl.get("bar", True):
            x0, x1, y = tl["x0"], tl["x1"], tl["y"]
            a = M.ease_out(u / 0.3)
            d.rounded_rectangle([x0, y - 9, x1, y + 9], 9, fill=CREAM + (int(70 * a),))
            g = M.ease((t - tl["t"] - 0.35) / tl["dur"])
            xe = x0 + (x1 - x0) * g
            if g > 0:
                d.rounded_rectangle([x0, y - 9, max(x0 + 18, xe), y + 9], 9, fill=YEL + (int(255 * a),))
            r = 30
            d.ellipse([xe - r, y - r, xe + r, y + r], fill=YEL + (int(255 * a),), outline=(60, 40, 30, int(255 * a)), width=6)
            for xx in (x0, x1):
                d.line([xx, y - 34, xx, y + 34], fill=CREAM + (int(160 * a),), width=6)
        # подписи
        if lab_for is not None:
            label(out, lab_for, *L["for"]["at"], L["for"]["t"], t)
        label(out, lab_sep, *L["separate"]["at"], L["separate"]["t"], t)
        label(out, lab_adult, *L["adult"]["at"], L["adult"]["t"], t)
        label(out, lab_grow, *L["grow"]["at"], L["grow"]["t"], t)
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
        for i, t in enumerate(cfg.get("preview_at") or [1.0, 3.0, 5.0, T - 0.05]):
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
