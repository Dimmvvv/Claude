#!/usr/bin/env python3
"""
«Показываем нашу работу»: окна-карточки на фоне вставок — запись экрана (кадры) и скриншоты,
по желанию в блюре. Окна приходят по очереди под слова, фон стоит, наезд только у карточек.

    python3 make_collage.py scene.json [--preview]

scene.json:
{
  "duration": 5.18, "out": "work/x.mp4", "bg": "vignette-red",
  "items": [
    {"frames": "work/work_show/rec", "t": 0.1, "at": [1500, 1080], "w": 2300, "rot": 0, "enter": "pop"},
    {"img": "work/work_show/t1.png", "blur": 12, "t": 2.3, "at": [3000, 700], "w": 1100, "rot": -5, "enter": "right"}
  ]
}
"title": "Очень странные дела" — фирменная плашка с названием сериала (как в бренде; старое имя ключа — pill_st).
frames — папка PNG-кадров (30 к/с, уже обрезаны/заблюрены ffmpeg), img — картинка; blur — радиус
гауссова размытия в пикселях исходной картинки (чтобы текст не читался); w — ширина карточки в кадре 4K.
enter: pop (вырастает с перелётом), right / left / up (въезжает с проявлением).
"""
import glob, json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_polaroids as mp  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30


def frame_card(content_w, content_h, w):
    """Маска скруглённого окна и белая кайма (как у наклейки во вставках)."""
    bw = round(M.WIN_BORDER * w); rad = round(M.WIN_RADIUS * w)
    cw, ch = w - 2 * bw, round((w - 2 * bw) * content_h / content_w)
    sw_, sh_ = w, ch + 2 * bw
    outer = Image.new("L", (sw_, sh_), 0); ImageDraw.Draw(outer).rounded_rectangle([0, 0, sw_ - 1, sh_ - 1], rad + bw, fill=255)
    inner = Image.new("L", (cw, ch), 0); ImageDraw.Draw(inner).rounded_rectangle([0, 0, cw - 1, ch - 1], rad, fill=255)
    pad = int(0.08 * w)
    sh = Image.new("L", (sw_ + 2 * pad, sh_ + 2 * pad), 0); sh.paste(outer.point(lambda v: int(v * 0.6)), (pad, pad))
    sh = sh.filter(ImageFilter.GaussianBlur(0.03 * w))
    return dict(bw=bw, cw=cw, ch=ch, outer=outer, inner=inner, shd=sh)


def build(cfg, bg):
    T = cfg["duration"]
    items = []
    for i, it in enumerate(cfg["items"]):
        it = dict(it, i=i)
        if it.get("frames"):
            it["paths"] = sorted(glob.glob(os.path.join(it["frames"], "*.png")))
            first = Image.open(it["paths"][0])
            src_w, src_h = first.size
        else:
            im = Image.open(it["img"]).convert("RGB")
            if it.get("blur"):
                im = im.filter(ImageFilter.GaussianBlur(it["blur"]))
            it["still"] = im; src_w, src_h = im.size
        it.update(frame_card(src_w, src_h, int(it["w"])))
        if it.get("still") is not None:
            it["still"] = it["still"].resize((it["cw"], it["ch"]), Image.LANCZOS)
        items.append(it)

    def content(it, u):
        if it.get("still") is not None:
            return it["still"]
        k = min(len(it["paths"]) - 1, max(0, int(u * FPS)))
        return Image.open(it["paths"][k]).convert("RGB").resize((it["cw"], it["ch"]), Image.BILINEAR)

    def frame(t):
        out = bg.copy()
        z = 1 + M.DRIFT * 0.8 * (t / T)                       # наезд — только карточки, фон стоит
        for it in items:
            u = t - it["t"]
            if u < 0:
                continue
            tx, ty = it["at"]; rot = it.get("rot", 0)
            enter = it.get("enter", "pop")
            if enter == "pop":                                   # вырастает с небольшим перелётом
                p = M.pop(u, M.WIN_POP, M.OVERSHOOT_SMALL)
                s = M.WIN_FROM + (1 - M.WIN_FROM) * p; x, y = tx, ty + 40 * (1 - p)
                ang = rot + M.WIN_TILT * (1 - M.ease_out(u / (M.WIN_POP * 1.3)))
                op = M.ease_out(u / M.APPEAR)
            else:                                                # въезжает коротко с проявлением
                p = M.pop(u, M.WIN_SLIDE, M.WIN_SLIDE_OVERSHOOT)
                dx, dy = {"right": (1, 0), "left": (-1, 0), "up": (0, 1)}[enter]
                d = M.WIN_SLIDE_DIST * it["w"]
                x, y = tx + dx * d * (1 - p), ty + dy * d * (1 - p)
                s = 1.0
                ang = rot + dx * 5 * (1 - M.ease_out(u / M.WIN_SLIDE))
                op = M.ease_out(u / M.WIN_FADE)
            ang += 0.5 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + it["i"])   # фон: < 5% главного
            x = W / 2 + (x - W / 2) * z; y = H / 2 + (y - H / 2) * z; s *= z
            card = Image.new("RGBA", it["outer"].size, (255, 255, 255, 0))
            card.paste((255, 255, 255, 255), (0, 0), it["outer"])
            card.paste(content(it, u), (it["bw"], it["bw"]), it["inner"])
            if s != 1:
                card = card.resize((max(2, round(card.width * s)), max(2, round(card.height * s))), Image.BILINEAR)
            card = card.rotate(ang, Image.BICUBIC, expand=True)
            if op < 1:
                card.putalpha(card.getchannel("A").point(lambda v: int(v * op)))
            lift = 1 - M.ease_out(u / M.STICKER_LAND)
            sh = it["shd"]; ss = s * (1 + 0.06 * lift)
            sh = sh.resize((max(2, round(sh.width * ss)), max(2, round(sh.height * ss))), Image.BILINEAR)
            sh = sh.rotate(ang, Image.BILINEAR, expand=True).point(lambda v: int(v * op))
            out.paste((0, 0, 0), (round(x - sh.width / 2), round(y - sh.height / 2 + (0.015 + 0.04 * lift) * card.height)), sh)
            out.paste(card, (round(x - card.width / 2), round(y - card.height / 2)), card)
        return out

    return frame


_F = None


def scene_bg(cfg):
    bg = mp.scene_bg(cfg)
    if cfg.get("pill_st"):                      # то же, что "title": фирменная плашка (старое имя ключа)
        cfg = dict(cfg, title=cfg["pill_st"])
    if cfg.get("title") and cfg.get("bg", "").startswith("vignette-"):
        import make_insert as mi
        mi.set_format("long")
        bg = mi.draw_pill(bg, cfg["title"])     # шрифт и вид — как в бренде (как у «Теории Большого взрыва»)
    return bg


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
        frame = build(cfg, scene_bg(cfg))
        for i, t in enumerate(cfg.get("preview_at") or [0.3, 1.5, 2.6, T - 0.05]):
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
