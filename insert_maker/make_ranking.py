#!/usr/bin/env python3
"""
Список/рейтинг на нашем фоне: карточка-наклейка, выделения по таймкодам,
рядом с выделенными строками появляются лица-стикеры.

    python3 make_ranking.py scene.json [--preview]

scene.json:
{
  "image": "work/forbes_top.png", "duration": 18, "bg": "blue", "source": "Forbes", "out": "work/x.mp4",
  "steps": [
    {"t": 1.0, "sel": "1:1-1:-1"},
    {"t": 6.0, "sel": "5:1-7:-1", "face": {"img": "work/faces/parsons.jpg", "crop": [360,255,235], "at": [1000, null]}}
  ],
  "dim_at": 5.6,          # с этого момента невыделенное гаснет (по умолчанию — со 2-го шага)
  "pulse_at": 15.3        # все лица одновременно «подпрыгивают» (необязательно)
}
face.crop = [cx, cy, r] круга на фото; face.at = [x, y] центра на скриншоте (y=null — по центру выделения);
face.d — диаметр в пикселях скриншота (по умолчанию 300); face.rot — наклон в покое.
"format": "short" — Shorts 9:16 (2160×3840); "bg", "title" — фон и плашка, как в make_insert;
"motion": "spring" — появления на пружине вместо кривой с перелётом.
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import motion as M  # noqa: E402

W, H = mi.W, mi.H
FPS = 30


def build(cfg):
    global W, H
    mi.set_format(cfg.get("format", "long")); W, H = mi.W, mi.H
    LAY = mi.LAY
    M.STYLE = cfg.get("motion", "ease")
    shot = Image.open(cfg["image"]).convert("RGB")
    info = mi.detect_layout(shot)
    lines = info["lines"]
    T = cfg["duration"]

    K = min(W * cfg.get("card_w", LAY["card_w"]) / shot.width,
            H * cfg.get("card_h", 0.78 if cfg.get("format", "long") == "long" else LAY["card_h"]) / shot.height)
    cw, ch = round(shot.width * K), round(shot.height * K)
    A = np.asarray(shot.resize((cw, ch), Image.LANCZOS), np.float32)
    bgc = np.array(info["bg"], np.float32)
    B = np.asarray(Image.fromarray(A.astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.3 * K)), np.float32)
    B = B * 0.38 + bgc * 0.62
    hmed = info["hmed"]; pad = 0.10 * hmed
    xs = np.arange(cw, dtype=np.float32)[None, :]

    steps = []
    for st in cfg["steps"]:
        L0, W0, L1, W1 = mi.parse_sel(st["sel"], lines)
        rects = []
        for li in range(L0, L1 + 1):
            l = lines[li]; ws = l["words"]
            xa = ws[W0][0] if li == L0 else ws[0][0]
            xb = ws[W1][1] if li == L1 else ws[-1][1]
            rects.append([(xa - pad) * K, (l["base"] - info["asc"] - 0.12 * hmed) * K,
                          (xb + pad) * K, (l["base"] + 0.34 * hmed) * K])
        keep = Image.new("L", (cw, ch), 0); kd = ImageDraw.Draw(keep)
        for r in rects:
            kd.rectangle([r[0] - 4, r[1] - 4, r[2] + 4, r[3] + 4], fill=255)
        keep = np.asarray(keep.filter(ImageFilter.GaussianBlur(3 * K)), np.float32)[..., None] / 255
        segs, tot = [], 0.0
        for r in rects:
            segs.append((r[0], r[2], int(r[1]), int(r[3]), tot)); tot += r[2] - r[0]
        face = None
        if st.get("face"):
            f = st["face"]
            cx, cy, rr = f["crop"]
            d = round(f.get("d", 300) * K)
            bw = round(d * 0.06)
            ph = Image.open(f["img"]).convert("RGB").crop((cx - rr, cy - rr, cx + rr, cy + rr)).resize((d, d), Image.LANCZOS)
            S = d + 2 * bw
            stk = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ImageDraw.Draw(stk).ellipse([0, 0, S - 1, S - 1], fill=(255, 255, 255, 255))
            m = Image.new("L", (d, d), 0); ImageDraw.Draw(m).ellipse([0, 0, d - 1, d - 1], fill=255)
            stk.paste(ph, (bw, bw), m)
            sp = round(S * 0.25)
            sh = Image.new("L", (S + 2 * sp, S + 2 * sp), 0)
            ImageDraw.Draw(sh).ellipse([sp, sp, sp + S, sp + S], fill=170)
            sh = sh.filter(ImageFilter.GaussianBlur(S * 0.07))
            ax, ay = f.get("at", [None, None])
            ycen = (min(r[1] for r in rects) + max(r[3] for r in rects)) / 2
            face = dict(stk=stk, sh=sh, x=(ax * K if ax is not None else cw * 0.7),
                        y=(ay * K if ay is not None else ycen), rot=f.get("rot", 0.0),
                        t=st["t"] + f.get("delay", M.FACE_DELAY))
        steps.append(dict(t=st["t"], segs=segs, tot=tot, keep=keep, face=face))

    dim_at = cfg.get("dim_at", steps[1]["t"] - 0.4 if len(steps) > 1 else 99)
    pulse_at = cfg.get("pulse_at")

    def sweep(st, p, feather):
        m = np.zeros((ch, cw), np.float32)
        dist = p * (st["tot"] + feather * len(st["segs"]))
        for j, (x0, x1, y0, y1, off) in enumerate(st["segs"]):
            v = np.clip((x0 + dist - off - feather * j - xs) / feather + 0.5, 0, 1) * ((xs >= x0 - 1) & (xs <= x1 + 1))
            m[max(0, y0):y1] = np.maximum(m[max(0, y0):y1], v)
        return m

    def card(t):
        img = A.copy()
        dim = mi.ease((t - dim_at) / M.DIM)
        if dim > 0:
            keep = np.zeros((ch, cw, 1), np.float32)
            for st in steps:
                u = mi.ease((t - st["t"] + 0.1) / 0.5)
                if u > 0:
                    keep = np.maximum(keep, st["keep"] * u)
            img = img + (B - img) * (dim * (1 - keep))
        for st in steps:
            p = mi.ease((t - st["t"]) / M.HIGHLIGHT)
            if p > 0:
                m = sweep(st, p, 6 * K)[..., None]
                img = img * (1 - m * (1 - mi.HL_COLOR / 255))
        out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGBA")
        for i, st in enumerate(steps):
            f = st["face"]
            if not f:
                continue
            p = t - f["t"]
            if p <= 0:
                continue
            sc = M.pop(p, M.FACE_POP, M.OVERSHOOT_SMALL, M.SPRING_FACE)
            if pulse_at is not None and 0 < t - pulse_at - M.PULSE_STAGGER * i < 0.5:
                sc *= 1 + M.PULSE * math.sin(math.pi * (t - pulse_at - M.PULSE_STAGGER * i) / 0.5)
            ang = f["rot"] + (-M.FACE_TILT if i % 2 == 0 else M.FACE_TILT) * (1 - mi.ease_out(p / M.FACE_TURN)) \
                + M.FACE_SWAY * math.sin(2 * math.pi * t / M.FACE_SWAY_PERIOD + i * 1.7) * mi.ease(p / 1.5)
            op = mi.ease_out(p / 0.18)
            lift = 1 - mi.ease_out(p / M.FACE_LAND)
            if sc < 0.02:
                continue
            s = f["stk"].resize((max(2, round(f["stk"].width * sc)),) * 2, Image.LANCZOS).rotate(ang, Image.BICUBIC, expand=True)
            if op < 1:
                s.putalpha(s.getchannel("A").point(lambda v: int(v * op)))
            shs = sc * (1 + 0.12 * lift)
            sh = f["sh"].resize((max(2, round(f["sh"].width * shs)),) * 2, Image.BILINEAR)
            sh = sh.point(lambda v: int(v * op * (0.55 + 0.25 * (1 - lift))))
            dy = (0.03 + 0.10 * lift) * f["stk"].width * sc
            out.paste((0, 0, 0, 255), (round(f["x"] - sh.width / 2), round(f["y"] - sh.height / 2 + dy)), sh)
            out.alpha_composite(s, (round(f["x"] - s.width / 2), round(f["y"] - s.height / 2)))
        return out.convert("RGB")

    # оформление (как в make_insert --intro sticker)
    rad = int(0.012 * cw); bw = int(0.022 * cw)
    sw_, sh_ = cw + 2 * bw, ch + 2 * bw
    alpha = Image.new("L", (cw, ch), 0); ImageDraw.Draw(alpha).rounded_rectangle([0, 0, cw - 1, ch - 1], rad, fill=255)
    st_alpha = Image.new("L", (sw_, sh_), 0); ImageDraw.Draw(st_alpha).rounded_rectangle([0, 0, sw_ - 1, sh_ - 1], rad + bw, fill=255)
    sp = int(0.07 * cw)
    st_shadow = Image.new("L", (sw_ + 2 * sp, sh_ + 2 * sp), 0)
    ImageDraw.Draw(st_shadow).rounded_rectangle([sp, sp, sp + sw_, sp + sh_], rad + bw, fill=165)
    st_shadow = st_shadow.filter(ImageFilter.GaussianBlur(0.02 * cw))

    bg = mi.load_bg(cfg.get("bg", "blue"), cfg.get("title"))
    chroma = cfg.get("bg") == "chroma"
    cap_label, cap_text, cap_line = mi.caption_colors(bg)
    cap = None
    if cfg.get("source"):
        cap = Image.new("RGBA", (W, 200), (0, 0, 0, 0)); cd = ImageDraw.Draw(cap)
        fl = ImageFont.truetype(mi.body_font_path(), 34); x = LAY["cap_x"]
        for c in "ИСТОЧНИК":
            cd.text((x, 100), c, font=fl, fill=cap_label, anchor="lm"); x += fl.getlength(c) + 6
        x += 28; cd.line([x, 70, x, 130], fill=cap_line, width=2); x += 32
        cd.text((x, 100), cfg["source"], font=ImageFont.truetype(mi.body_font_path(), 44), fill=cap_text, anchor="lm")
    t_cap = cfg.get("source_at", steps[0]["t"] + 0.5)

    def frame(t):
        out = bg.copy()
        if cap is not None:
            ca = mi.ease_out((t - t_cap) / M.CAPTION)
            if ca > 0:
                c = cap.copy(); c.putalpha(c.getchannel("A").point(lambda v: int(v * ca)))
                out.paste(c, (0, int(LAY["cap_y"] + 20 * (1 - ca))), c)
        img = card(t)
        pop = M.pop(t, M.STICKER_POP)
        s = (0.95 + 0.05 * (t / T)) * (0.4 + 0.6 * pop)
        ang = M.STICKER_TILT * (1 - mi.ease_out(t / M.STICKER_TURN))
        op = mi.ease_out(t / M.APPEAR)
        lift = 1 - mi.ease_out(t / M.STICKER_LAND)
        cx, cy = W / 2, H * (LAY["sticker_cy"] - 0.02 * (t / T))
        st = Image.new("RGBA", (sw_, sh_), (255, 255, 255, 0))
        st.paste((255, 255, 255, 255), (0, 0), st_alpha)
        st.paste(img, (bw, bw), alpha)
        w2, h2 = max(2, round(sw_ * s)), max(2, round(sh_ * s))
        st = st.resize((w2, h2), Image.LANCZOS)
        if abs(ang) > 0.01:
            st = st.rotate(ang, Image.BICUBIC, expand=True)
        if op < 1:
            st.putalpha(st.getchannel("A").point(lambda v: int(v * op)))
        ss = s * (1 + 0.08 * lift)
        shd = st_shadow.resize((max(2, round(st_shadow.width * ss)), max(2, round(st_shadow.height * ss))), Image.BILINEAR)
        if abs(ang) > 0.01:
            shd = shd.rotate(ang, Image.BILINEAR, expand=True)
        shd = shd.point(lambda v: int(v * op * (0.75 + 0.25 * (1 - lift))))
        dy = (0.012 + 0.05 * lift) * h2
        if not chroma:
            out.paste((0, 0, 0), (round(cx - shd.width / 2), round(cy - shd.height / 2 + dy)), shd)
        out.paste(st, (round(cx - st.width / 2), round(cy - st.height / 2)), st)
        return out

    return frame


_F = None


def _init(cfg):
    global _F
    _F = build(cfg)


def _render(t):
    return _F(t).tobytes()


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    T = cfg["duration"]
    global W, H
    mi.set_format(cfg.get("format", "long")); W, H = mi.W, mi.H
    stem = os.path.splitext(cfg.get("out", sys.argv[1]))[0]
    if "--preview" in sys.argv:
        frame = build(cfg)
        ts = [0.3] + [st["t"] + 0.9 for st in cfg["steps"]] + [T - 0.05]
        for i, t in enumerate(ts):
            p = f"{stem}_preview_{i}.png"; frame(t).resize((W // 2, H // 2), Image.LANCZOS).save(p); print("->", p, f"t={t:.2f}")
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
