#!/usr/bin/env python3
"""
Мини-расчёт на фоне вставок в три шага (один фокус за раз):
  1) вырезка-объект шлёпается крупно, рядом цена и подпись;
  2) объект уезжает в угол маленьким «жетоном», выходит поляроид, справа срок и счётчик;
  3) поляроид отходит влево, выходит второй поляроид со счётчиком-подписью, справа итог.

    python3 make_scoops.py scene.json [--preview]

scene.json — см. work/scoops/scene.json. Тексты: "font": "st" (Playfair заглавными) или "body" (Gilroy/Inter);
"count": {"to": 3600, "dur": 1.2, "fmt": "{}%"} — число докручивается; "out" — время ухода;
"overlay": {"scene": "<zoomrow.json>", "t", "out", "out_dur", "shade"} — окно-таблица с приближением поверх сцены;
"object".top: true — вырезка поверх карточек (фон под ней притемняется); "stickers": [...] как в make_levels;
"pulse": t — у текста «удар» масштаба, у карточки подскок с встряской (реакция). "object" необязателен.
"""
import json, math, os, sys, subprocess
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_polaroids as mp  # noqa: E402
import make_levels as ml  # noqa: E402
import make_collage as mc  # noqa: E402
import make_taxcredit as mt  # noqa: E402
import motion as M  # noqa: E402

W, H, FPS = 3840, 2160, 30
COLORS = {"cream": ml.CREAM, "yellow": ml.HL_YELLOW}


def num(v):
    return f"{int(v):,}".replace(",", " ")


def text_img(spec, txt=None):
    txt = spec["text"] if txt is None else txt
    col = COLORS.get(spec.get("color", "cream"))
    if spec.get("font", "body") == "st":
        im = ml.text_sprite(txt.upper(), lambda sz, ch: ml.st_font(sz, ch), spec["size"], col, sp=0.04, lining=True)
    else:
        im = ml.text_sprite(txt, lambda sz, ch: ml.body_font(sz), spec["size"], col)
    if spec.get("alpha", 1) < 1:
        im = ml.fade(im, spec["alpha"])
    return im


def lerp(a, b, q):
    return a + (b - a) * q


def build(cfg, bg):
    T = cfg["duration"]
    # --- объект-вырезка
    ob = cfg.get("object")
    if ob:
        obj = Image.open(ob["img"]).convert("RGBA")
        k = ob["w"] / obj.width
        obj = obj.resize((round(obj.width * k), round(obj.height * k)), Image.LANCZOS)
        sho = mt.soft_shadow(obj)
    # --- поляроиды (без гирлянды)
    cards = []
    for i, cs in enumerate(cfg["cards"]):
        c, card, _ = mt.polaroid(cs, 5 + 4 * i, lights=False)
        cards.append((c, card, mt.soft_shadow(card)))
    # --- тексты
    texts = []
    for ts in cfg["texts"]:
        if ts.get("max_w"):
            im = text_img(ts)
            if im.width > ts["max_w"]:
                ts = dict(ts, size=int(ts["size"] * ts["max_w"] / im.width))
        static = None if ts.get("count") else text_img(ts)
        texts.append((ts, static))

    def move_state(spec, t):
        """позиция/масштаб с учётом переездов "moves": [{"t", "dur", "at", "s"}]"""
        x, y = spec["at"]; s = 1.0
        for mv in spec.get("moves", []):
            q = M.ease((t - mv["t"]) / mv.get("dur", 0.8))
            if q <= 0:
                break
            x, y = lerp(x, mv["at"][0], q), lerp(y, mv["at"][1], q); s = lerp(s, mv.get("s", s), q)
        return x, y, s

    def out_fade(spec, t):
        if spec.get("out") is None:
            return 1.0
        return 1 - M.ease((t - spec["out"]) / spec.get("out_dur", 0.4))

    stickers = ml.load_stickers(cfg.get("stickers", []))

    def draw_object(out, t):
        u = t - ob["t"] if ob else -1
        if u >= 0:
            p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
            x, y, sm = move_state(ob, t)
            s = (1 + M.LEVEL_SLAP * (1 - p)) * sm
            ang = ob.get("rot", 0) - 8 * (1 - M.ease_out(u / M.STICKER_TURN))
            ang += M.FACE_SWAY * 0.6 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + 1)
            mt.place(out, obj, sho, x, y, s, ang, M.ease_out(u / M.APPEAR) * out_fade(ob, t),
                     1 - M.ease_out(u / M.STICKER_LAND))

    # «overlay»: окно-таблица из make_zoomrow поверх сцены (своё приближение и выделения).
    # Рисуем его на чёрном и на белом фоне → точная прозрачность вместе с тенью.
    ovc = cfg.get("overlay")
    if ovc:
        import make_zoomrow as mz
        zc = json.load(open(ovc["scene"], encoding="utf-8")) if isinstance(ovc.get("scene"), str) else ovc["scene"]
        z_black = mz.build(zc, Image.new("RGB", (W, H), (0, 0, 0)))
        z_white = mz.build(zc, Image.new("RGB", (W, H), (255, 255, 255)))

    def frame(t):
        out = frame_base(t)
        if ovc and ovc["t"] <= t:
            u = t - ovc["t"]
            f = 1 - M.ease((t - ovc["out"]) / ovc.get("out_dur", 0.4)) if t > ovc["out"] else 1.0
            if f > 0:
                sh = M.ease(u / 0.4) * f * ovc.get("shade", 0.0)      # сцена позади притемняется
                o = np.asarray(out, np.float32) * (1 - sh)
                Bk = np.asarray(z_black(u), np.float32); Wh = np.asarray(z_white(u), np.float32)
                A = 1 - (Wh - Bk).mean(axis=2, keepdims=True) / 255
                out = Image.fromarray(np.clip(f * Bk + (1 - f * A) * o, 0, 255).astype(np.uint8))
        return out

    def frame_base(t):
        out = bg.copy()
        ml.draw_stickers(out, stickers, t)
        top = bool(ob and ob.get("top"))
        # объект
        u = t - ob["t"] if (ob and not top) else -1
        if u >= 0:
            p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
            x, y, sm = move_state(ob, t)
            s = (1 + M.LEVEL_SLAP * (1 - p)) * sm
            ang = ob.get("rot", 0) - 8 * (1 - M.ease_out(u / M.STICKER_TURN))
            ang += M.FACE_SWAY * 0.6 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + 1)
            mt.place(out, obj, sho, x, y, s, ang, M.ease_out(u / M.APPEAR) * out_fade(ob, t),
                     1 - M.ease_out(u / M.STICKER_LAND))
        # поляроиды
        for (c, card, sh), cs in zip(cards, cfg["cards"]):
            u = t - cs["t"]
            if u < 0:
                continue
            p = M.pop(u, M.STICKER_POP, M.OVERSHOOT_SMALL)
            x, y, sm = move_state(cs, t)
            s = (M.WIN_FROM + (1 - M.WIN_FROM) * p) * sm
            if cs.get("pulse") is not None:                  # реакция: короткий подскок + встряска
                pu = t - cs["pulse"]
                if 0 < pu < 0.5:
                    s *= 1 + 0.07 * math.sin(math.pi * pu / 0.5)
            ang = cs.get("rot", 0) + (10 if cs.get("rot", 0) < 0 else -10) * (1 - M.ease_out(u / M.STICKER_TURN))
            ang += M.FACE_SWAY * 0.8 * math.sin(2 * math.pi * u / M.FACE_SWAY_PERIOD + cs["at"][0])
            if cs.get("pulse") is not None and 0 < t - cs["pulse"] < 0.5:
                pu = (t - cs["pulse"]) / 0.5
                ang += 3.5 * math.sin(pu * 4 * math.pi) * (1 - pu)
            im = card
            cnt = cs.get("count")
            if cnt and t >= cnt["t"]:
                q = M.ease_out((t - cnt["t"]) / cnt.get("dur", 1.2))
                full = cnt.get("prefix", "") + num(cnt["to"])
                txt = cnt.get("prefix", "") + num(round(cnt["to"] * q / cnt.get("step", 1)) * cnt.get("step", 1))
                im = card.copy(); mp.st_caption(im, c, txt, full)
            mt.place(out, im, sh, x, y, s, ang, M.ease_out(u / M.APPEAR) * out_fade(cs, t),
                     1 - M.ease_out(u / M.STICKER_LAND))
        if top:                                              # вырезка поверх карточек (пока она на экране, карточки чуть темнее)
            dq = M.ease((t - ob["t"]) / 0.35) * out_fade(ob, t) if t >= ob["t"] else 0.0
            if dq > 0:
                shade = Image.new("RGBA", out.size, (0, 0, 0, int(110 * dq)))
                out.paste(shade, (0, 0), shade)
            draw_object(out, t)
        # тексты: встают снизу с лёгким перелётом, уходят вверх
        for ts, static in texts:
            u = t - ts["t"]
            if u < 0:
                continue
            q = M.pop(u, M.WORD_IN, M.OVERSHOOT_SMALL)
            op = M.ease_out(u / 0.25) * out_fade(ts, t)
            if op <= 0.01:
                continue
            if ts.get("count"):
                cn = ts["count"]
                v = cn["to"] * M.ease_out((t - ts["t"] - cn.get("delay", 0.1)) / cn.get("dur", 1.2))
                step = cn.get("step", 1)
                im = text_img(ts, cn.get("fmt", "{}").format(num(round(max(0, v) / step) * step)))
            else:
                im = static
            sc = 1.0
            if ts.get("pulse") is not None:                  # «удар» на ключевом слове 1,0 → 1,08 → 1,0
                pu = t - ts["pulse"]
                if 0 < pu < 0.45:
                    sc = 1 + 0.08 * math.sin(math.pi * pu / 0.45)
            if sc != 1.0:
                im = im.resize((round(im.width * sc), round(im.height * sc)), Image.BICUBIC)
            im = ml.fade(im, op)
            rise = (1 - q) * 0.35 * ts["size"]
            if ts.get("out") is not None and t > ts["out"]:
                rise -= 40 * M.ease((t - ts["out"]) / ts.get("out_dur", 0.4))
            x, y = ts["at"]
            x0 = x - (im.width / 2 if ts.get("align") == "center" else 0)
            out.paste(im, (round(x0), round(y - im.height / 2 + rise)), im)
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
        for i, t in enumerate(cfg.get("preview_at") or [1.0, 3.0, T - 0.05]):
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
