#!/usr/bin/env python3
"""
Крупные слова поверх ведущего (под жест «вот тут — ЖИЛ»): буквы приходят каскадом, слово стоит,
в конце уходит. Шрифт и цвет — как подписи поляроидов (Playfair Display Bold, красный, светлая обводка).

    python3 make_words.py scene.json [--preview]

scene.json:
{
  "duration": 2.6, "out": "work/hook/word_zhil.mp4", "bg": "chroma",
  "preview_bg": "work/hook/frame.webp",
  "words": [{"text": "Жил", "t": 0.1, "at": [3150, 980], "size": 330, "out": 2.2}]
}
at — центр слова в кадре 3840×2160; size — кегль в px; out — когда слово уходит (необязательно).
"""
import json, math, os, sys, subprocess
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import make_polaroids as mp  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
STROKE = (246, 238, 218)            # светлая обводка — читается на синей стене и на любом видео


def letter_sprites(text, size):
    """Спрайты букв (RGBA) и их x-смещения от центра слова."""
    text = text.upper()
    sp = 0.05 * size
    fonts = [mp._st_font(size, mi.is_cyr(ch)) for ch in text]
    adv = [f.getlength(ch) for f, ch in zip(fonts, text)]
    tw = sum(adv) + sp * (len(text) - 1)
    sw = max(2, round(size * M.WORD_STROKE))
    out, x = [], -tw / 2
    for ch, f, a in zip(text, fonts, adv):
        pad = sw + int(0.3 * size)
        im = Image.new("RGBA", (int(a) + 2 * pad, int(1.5 * size) + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((pad, pad + 0.75 * size), ch, font=f, fill=mp.ST_RED, anchor="ls",
                                stroke_width=sw, stroke_fill=STROKE)
        out.append(dict(im=im, dx=x + a / 2, pad=pad, base=pad + 0.75 * size, a=a))
        x += a + sp
    return out


def build(cfg, bg):
    words = []
    for wd in cfg["words"]:
        words.append(dict(wd, letters=letter_sprites(wd["text"], wd.get("size", 300))))

    def frame(t):
        out = bg.copy()
        for wd in words:
            cx, cy = wd["at"]; size = wd.get("size", 300)
            n = len(wd["letters"])
            for k, L in enumerate(wd["letters"]):
                u = t - wd["t"] - k * M.WORD_STAGGER
                if u < 0:
                    continue
                p = M.pop(u, M.WORD_IN, M.OVERSHOOT_SMALL)          # положение и размер — с перелётом
                op = M.ease_out(u / M.WORD_FADE)                     # прозрачность — без
                s = M.WORD_FROM + (1 - M.WORD_FROM) * p
                dy = M.WORD_RISE * size * (1 - p)
                wo = wd.get("out")
                if wo is not None and t > wo:                        # уход: каскадом, вниз и в прозрачность
                    e = M.ease_in((t - wo - (n - 1 - k) * M.WORD_STAGGER * 0.6) / M.WORD_OUT)
                    op *= 1 - e; dy += 0.25 * size * e; s *= 1 - 0.15 * e
                if op <= 0.01:
                    continue
                dy += 0.012 * size * math.sin(2 * math.pi * (t - wd["t"]) / M.FACE_SWAY_PERIOD + k * 0.6)
                im = L["im"]
                if s != 1:
                    im = im.resize((max(2, round(im.width * s)), max(2, round(im.height * s))), Image.LANCZOS)
                if op < 1:
                    im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * op)))
                # масштаб от базовой линии буквы
                x = cx + L["dx"] - im.width / 2
                y = cy + 0.3 * size - L["base"] * s + dy
                out.paste(im, (round(x), round(y)), im)
        return out

    return frame


_F = None


def _init(cfg):
    global _F
    _F = build(cfg, mp.scene_bg(cfg))


def _render(t):
    return _F(t).tobytes()


def main():
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    T = cfg["duration"]
    stem = os.path.splitext(cfg["out"])[0]
    if "--preview" in sys.argv:
        pb = cfg.get("preview_bg")
        bg = Image.open(pb).convert("RGB").resize((W, H), Image.LANCZOS) if pb else mp.scene_bg(cfg)
        frame = build(cfg, bg)
        for i, t in enumerate(cfg.get("preview_at") or [0.2, 0.35, 0.8, T - 0.2]):
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
