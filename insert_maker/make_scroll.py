#!/usr/bin/env python3
"""
Листание длинной страницы → маркер → наезд → перевод, на нашем фоне.

Исходник: скриншот страницы ЦЕЛИКОМ в высоком разрешении (файлом/zip, не картинкой в чат)
или снимок по ссылке: node tools/capture_page.js URL page.png

1. Вырезать зону вокруг цитаты и разметить слова (координаты --sel — внутри зоны):
     python3 make_scroll.py page.png --region 8250:10750 --detect
2. Превью / рендер:
     python3 make_scroll.py page.png --region 8250:10750 --sel 10:1-13:-1 --ru 'перевод' --preview
     python3 make_scroll.py page.png --region 8250:10750 --sel 10:1-13:-1 --ru 'перевод' --out work/x.mp4

Тайминг (по умолчанию 9 с): 0–0,5 появление · 0,3–2,9 листание · 3,0 маркер · 4,0–5,1 наезд ·
5,3–6,5 перевод · дальше удержание с медленным наездом.
"""
import argparse, os, sys, subprocess
from argparse import Namespace
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402

W, H = mi.W, mi.H
SHIFT = 2.0          # сдвиг расписания make_insert: его маркер стартует в 1,0 → у нас в 3,0
T_SCROLL = (0.3, 2.9)
T_ZOOM = (4.0, 5.1)


def region_path(args):
    y0, y1 = map(int, args.region.split(":"))
    stem = os.path.splitext(args.page)[0]
    p = f"{stem}_region_{y0}_{y1}.png"
    if not os.path.exists(p):
        Image.open(args.page).convert("RGB").crop((0, y0, Image.open(args.page).width, y1)).save(p)
    return p, y0, y1


def build(args):
    page = Image.open(args.page).convert("RGB")
    pw, ph = page.size
    rpath, ry0, ry1 = region_path(args)

    s1 = W * args.sheet_w / pw                   # экран/страница при обычном виде
    kd = s1 * args.zoom                          # детальный слой рисуем сразу в масштабе наезда
    margs = Namespace(image=rpath, sel=args.sel, ru=args.ru, source="", bg=args.bg,
                      duration=args.duration, fps=args.fps, card_w=0.62, hl_time=0.9,
                      pause=1.4, ru_time=1.2, dim=0.62, blur=1.3, font=args.font,
                      intro="fade", k_override=kd)
    _, info, meta = mi.build(margs)
    card_img, card_state = meta["card_img"], meta["card_state"]

    # центр выделения в координатах страницы
    rs = np.array(meta["hl_rects"], float)
    tcx = (rs[:, 0].min() + rs[:, 2].max()) / 2
    tcy = (rs[:, 1].min() + rs[:, 3].max()) / 2 + ry0
    start_y = args.start_y if args.start_y is not None else (H / 2) / s1   # верх страницы у верха кадра

    bg = Image.open(args.bg).convert("RGB")
    if bg.size != (W, H):
        bg = bg.resize((W, H), Image.LANCZOS)
    T = args.duration

    cap = None
    if args.source:
        cap = Image.new("RGBA", (W, 200), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cap)
        fl = mi.ImageFont.truetype(mi.INTER, 34)
        x = 338
        for c in "ИСТОЧНИК":
            cd.text((x, 100), c, font=fl, fill=mi.CAPTION_LABEL, anchor="lm"); x += fl.getlength(c) + 6
        x += 28; cd.line([x, 70, x, 130], fill=(60, 64, 96), width=2); x += 32
        cd.text((x, 100), args.source, font=mi.ImageFont.truetype(mi.INTER, 44), fill=mi.CAPTION_TEXT, anchor="lm")

    def camera(t):
        p = mi.ease((t - T_SCROLL[0]) / (T_SCROLL[1] - T_SCROLL[0]))
        q = mi.ease((t - T_ZOOM[0]) / (T_ZOOM[1] - T_ZOOM[0]))
        z = 1 + (args.zoom - 1) * q
        z *= 1 + 0.04 * max(0.0, t - T_ZOOM[1]) / max(0.1, T - T_ZOOM[1])     # медленный наезд в удержании
        fx = pw / 2 + (tcx - pw / 2) * q
        fy = start_y + (tcy - start_y) * p
        return fx, fy, s1 * z

    def place(out, src, k, oy, fx, fy, s, rise, op, vblur):
        """src: изображение в масштабе k относительно страницы, со сдвигом oy по y (пикс. страницы)."""
        cx, cy = W / 2, H / 2 + rise
        # видимая область → координаты src
        bx0, bx1 = (fx - cx / s) * k, (fx + (W - cx) / s) * k
        by0, by1 = (fy - cy / s - oy) * k, (fy + (H - cy) / s - oy) * k
        bx0, by0 = max(0.0, bx0), max(0.0, by0)
        bx1, by1 = min(float(src.width), bx1), min(float(src.height), by1)
        if bx1 - bx0 < 2 or by1 - by0 < 2:
            return
        X0 = cx + (bx0 / k - fx) * s
        Y0 = cy + (by0 / k + oy - fy) * s
        X1 = cx + (bx1 / k - fx) * s
        Y1 = cy + (by1 / k + oy - fy) * s
        size = (max(1, round(X1 - X0)), max(1, round(Y1 - Y0)))
        img = src.resize(size, Image.LANCZOS, box=(bx0, by0, bx1, by1))
        if vblur > 3:                                   # размытие движения при быстром листании
            f = min(vblur / 3, 40)
            img = img.resize((size[0], max(1, int(size[1] / f))), Image.BILINEAR).resize(size, Image.BILINEAR)
        mask = None if op >= 0.999 else Image.new("L", size, int(255 * op))
        out.paste(img, (round(X0), round(Y0)), mask)

    def frame(t):
        out = bg.copy()
        op = mi.ease_out(t / 0.5)
        rise = 60 * (1 - op)
        fx, fy, s = camera(t)
        _, fy_prev, s_prev = camera(t - 1 / args.fps)
        vblur = abs(fy - fy_prev) * s                  # сдвиг за кадр в пикселях экрана

        # тень листа
        sx0, sx1 = W / 2 + (0 - fx) * s, W / 2 + (pw - fx) * s
        sy0, sy1 = H / 2 + rise + (0 - fy) * s, H / 2 + rise + (ph - fy) * s
        q = 4
        sh = Image.new("L", (W // q, H // q), 0)
        ImageDraw.Draw(sh).rectangle([sx0 / q, (sy0 + 25) / q, sx1 / q, (sy1 + 25) / q], fill=int(150 * op))
        sh = sh.filter(ImageFilter.GaussianBlur(14)).resize((W, H), Image.BILINEAR)
        out.paste((0, 0, 0), (0, 0), sh)

        if cap is not None:
            ca = mi.ease_out((t - SHIFT - 1.5) / 0.6)
            if ca > 0:
                c = cap.copy(); c.putalpha(c.getchannel("A").point(lambda v: int(v * ca)))
                out.paste(c, (0, int(1917 + 20 * (1 - ca))), c)

        cs = card_state(t - SHIFT)
        if cs == (0.0, 0.0, 0.0):
            place(out, page, 1.0, 0.0, fx, fy, s, rise, op, vblur)
        else:
            # вокруг детального слоя — обычная страница (на случай, если зона меньше кадра)
            place(out, page, 1.0, 0.0, fx, fy, s, rise, op, 0)
            place(out, card_img(*cs), kd, ry0, fx, fy, s, rise, op, 0)
        return out

    return frame, info


_F = None


def _init(args):
    global _F
    _F = build(args)[0]


def _render(t):
    return _F(t).tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("--region", required=True, help="y0:y1 — зона вокруг цитаты в пикселях страницы")
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--sel", action="append")
    ap.add_argument("--ru", action="append")
    ap.add_argument("--start-y", type=float, default=None)
    ap.add_argument("--zoom", type=float, default=1.8)
    ap.add_argument("--sheet-w", type=float, default=0.62)
    ap.add_argument("--source", default="")
    ap.add_argument("--font", default="serif", choices=["serif", "sans", "sans-bold"])
    ap.add_argument("--bg", default=os.path.join(HERE, "assets", "bg_4k.png"))
    ap.add_argument("--duration", type=float, default=9.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    if args.detect:
        rp, _, _ = region_path(args)
        subprocess.run([sys.executable, os.path.join(HERE, "make_insert.py"), rp, "--detect"], check=True)
        return
    if not (args.sel and args.ru):
        sys.exit("нужны --sel и --ru (или --detect)")

    stem = os.path.splitext(args.page)[0]
    if args.preview:
        frame, _ = build(args)
        for i, t in enumerate([0.15, 1.6, 3.6, 4.6, 5.9, args.duration - 0.05]):
            p = f"{stem}_scroll_preview_{i}.png"
            frame(t).resize((1920, 1080), Image.LANCZOS).save(p)
            print("->", p, f"t={t:.2f}")
        return

    out = args.out or stem + "_scroll.mp4"
    n = int(round(args.duration * args.fps))
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    from multiprocessing import Pool
    with Pool(args.workers, initializer=_init, initargs=(args,)) as pool:
        for i, buf in enumerate(pool.imap(_render, [k / args.fps for k in range(n)], chunksize=4)):
            ff.stdin.write(buf)
            if i % 30 == 0:
                print(f"\r{i}/{n}", end="", flush=True)
    ff.stdin.close(); ff.wait()
    print(f"\r{n}/{n} -> {out}")


if __name__ == "__main__":
    main()
