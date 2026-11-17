#!/usr/bin/env python3
"""
Мини-история на фоне вставок: поляроид «до» → вырезка-объект в центре (шлепок + «нажатие») →
линия-стрелка тянется → поляроид «после» с подписью-счётчиком. Стикеры по бокам.

    python3 make_taxcredit.py scene.json [--preview]

scene.json:
{
  "duration": 5.2, "out": "work/tax/tax.mp4", "bg": "vignette-red", "title": "Очень странные дела",
  "card1": {"img": "...", "caption": "Джойс", "at": [1080, 1110], "w": 760, "rot": -5, "t": 0.25},
  "object": {"img": "work/tax/calc.png", "at": [1920, 1080], "w": 700, "rot": -3, "t": 1.2, "press": 1.9},
  "line": {"t": 2.3, "y": 1110},
  "card2": {"img": "...", "at": [2760, 1110], "w": 760, "rot": 4, "t": 2.8,
            "count": {"prefix": "+$", "value": 200, "t": 3.4}},
  "stickers": [...],                     # необязательно
  "lights": false,                       # без гирлянд на поляроидах
  object.tint: "paper"                   # вырезка в тонах старой бумаги
}
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_insert as mi  # noqa: E402
import make_polaroids as mp  # noqa: E402
import make_levels as ml  # noqa: E402
import make_collage as mc  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30


def soft_shadow(im):
    pad = int(0.1 * im.width)
    sh = Image.new("L", (im.width + 2 * pad, im.height + 2 * pad), 0)
    sh.paste(im.getchannel("A").point(lambda v: int(v * 0.55)), (pad, pad))
    return sh.filter(ImageFilter.GaussianBlur(0.035 * im.width))


def place(out, im, sh, x, y, s, ang, op, lift):
    """Элемент с тенью «приподнят → прилип»: масштаб s, поворот ang, прозрачность op."""
    if op <= 0.01 or s <= 0.01:
        return
    e = im.resize((max(2, round(im.width * s)), max(2, round(im.height * s))), Image.BILINEAR)
    e = ml.fade(e.rotate(ang, Image.BICUBIC, expand=True), op)
    k = s * (1 + 0.06 * lift)
    d = sh.resize((max(2, round(sh.width * k)), max(2, round(sh.height * k))), Image.BILINEAR)
    d = d.rotate(ang, Image.BILINEAR, expand=True).point(lambda v: int(v * op))
    out.paste((0, 0, 0), (round(x - d.width / 2), round(y - d.height / 2 + (0.015 + 0.05 * lift) * e.height)), d)
    out.paste(e, (round(x - e.width / 2), round(y - e.height / 2)), e)


def polaroid(spec, seed, lights=True):
    c = dict(spec, paper="old", seed=seed, caption_style="st")
    if spec.get("count"):
        c.pop("caption", None)                       # подпись-счётчик рисуется покадрово
    card = mp.make_card(c)
    bulbs = mp.make_lights(card, int(c["w"]), seed) if lights else []
    return c, card, bulbs


def paper_tint(im):
    """Перекрасить вырезку в тона старых поляроидов: тёмное → тёплый коричневый, светлое → кремовая бумага."""
    a = np.asarray(im, np.float32)
    L = (a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32))[..., None] / 255
    dark, light = np.array(M.TINT_DARK, np.float32), np.array(mp.PAPER_OLD[0], np.float32)
    rgb = dark * (1 - L) + light * L
    out = np.concatenate([rgb, a[..., 3:4]], axis=2)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def bulbs_bright(bulbs, u, t):
    br = []
    for b in bulbs:
        v = M.ease_out((u - M.STICKER_POP - b["k"] * M.LIGHT_STAGGER) / 0.3)
        v *= 1 - M.LIGHT_FLICKER + M.LIGHT_FLICKER * math.sin(2 * math.pi * t / b["per"] + b["ph"])
        br.append(max(0.0, v))
    return br


def build(cfg, bg):
    stickers = ml.load_stickers(cfg.get("stickers", []))
    lights = cfg.get("lights", True)
    c1, card1, bulbs1 = polaroid(cfg["card1"], 5, lights)
    c2, card2, bulbs2 = polaroid(cfg["card2"], 9, lights)
    obj = Image.open(cfg["object"]["img"]).convert("RGBA")
    if cfg["object"].get("tint") == "paper":
        obj = paper_tint(obj)
    sc = cfg["object"]["w"] / obj.width
    obj = obj.resize((round(obj.width * sc), round(obj.height * sc)), Image.LANCZOS)
    sh1, sh2, sho = soft_shadow(card1), soft_shadow(card2), soft_shadow(obj)
    cnt = cfg["card2"]["count"]
    cnt_font = ImageFont.truetype(mi.body_font_path(), round(0.15 * c2["w"]))      # наш шрифт (Gilroy / Inter)

    def card_at(spec, card, bulbs, sh, out, t, count=None):
        u = t - spec["t"]
        if u < 0:
            return
        p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
        s = M.WIN_FROM + (1 - M.WIN_FROM) * p
        ang = spec.get("rot", 0) + (10 if spec.get("rot", 0) < 0 else -10) * (1 - M.ease_out(u / M.STICKER_TURN))
        ang += M.FACE_SWAY * 0.8 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + spec["at"][0])
        im = mp.light_up(card, bulbs, bulbs_bright(bulbs, u, t)) if bulbs else card
        if count:
            q = M.ease_out((t - count["t"]) / M.CMP_GROW)
            if q > 0:
                if im is card:
                    im = card.copy()
                txt = count["prefix"] + str(int(round(count["value"] * q)))
                full = count["prefix"] + str(count["value"])
                d = ImageDraw.Draw(im)
                tw = cnt_font.getlength(full)                     # центрируем по итоговой ширине — цифры не прыгают
                d.text(((im.width - tw) / 2, spec["_cap_y"]), txt, font=cnt_font, fill=mp.ST_RED, anchor="lm")
        place(out, im, sh, spec["at"][0], spec["at"][1], s, ang, M.ease_out(u / M.APPEAR), 1 - M.ease_out(u / M.STICKER_LAND))

    def frame(t):
        out = bg.copy()
        ml.draw_stickers(out, stickers, t)
        # линия-стрелка от первой карточки ко второй (под объектом)
        ln = cfg["line"]
        q = M.ease((t - ln["t"]) / M.TAX_LINE)
        if q > 0:
            d = ImageDraw.Draw(out, "RGBA")
            x0 = cfg["card1"]["at"][0] + cfg["card1"]["w"] / 2 + 40
            x1 = cfg["card2"]["at"][0] - cfg["card2"]["w"] / 2 - 60
            y = ln["y"]; xe = x0 + (x1 - x0) * q
            k = x0
            while k < xe:                                         # пунктир
                d.line([k, y, min(k + 46, xe), y], fill=ml.CREAM + (230,), width=10)
                k += 76
            if q > 0.92:
                d.polygon([(xe + 16, y), (xe - 40, y - 30), (xe - 40, y + 30)], fill=ml.CREAM + (230,))
        card_at(c1, card1, bulbs1, sh1, out, t)
        # объект: шлепок, потом «нажатие»
        o = cfg["object"]; u = t - o["t"]
        if u >= 0:
            p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
            s = 1 + M.LEVEL_SLAP * (1 - p)
            pr = t - o["press"]
            if 0 < pr < M.TAX_PRESS:
                s *= 1 - 0.05 * math.sin(math.pi * pr / M.TAX_PRESS)
            ang = o.get("rot", 0) - 8 * (1 - M.ease_out(u / M.STICKER_TURN))
            ang += M.FACE_SWAY * 0.6 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + 1)
            place(out, obj, sho, o["at"][0], o["at"][1], s, ang, M.ease_out(u / M.APPEAR), 1 - M.ease_out(u / M.STICKER_LAND))
        card_at(c2, card2, bulbs2, sh2, out, t, count=cnt)
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
        for i, t in enumerate(cfg.get("preview_at") or [0.8, 1.6, 2.6, 3.3, T - 0.05]):
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
