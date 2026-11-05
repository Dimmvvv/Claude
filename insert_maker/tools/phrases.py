#!/usr/bin/env python3
"""
Тайминги из озвучки: где начинается каждая фраза и (примерно) нужное слово.
Без распознавания речи — только паузы в звуке (ffmpeg silencedetect) + текст закадра.

    python3 tools/phrases.py voice.m4a
    python3 tools/phrases.py voice.m4a --text text.txt --find Парсонс Галецки "Кунал Найяр"

Принимает любой звук или видео (wav, mp3, m4a, mov, mp4).
Вывод: таблица фраз (начало–конец), оценка времени слов, файл <voice>_timing.json
и картинка <voice>_wave.png (волна + границы фраз + найденные слова) для проверки глазами.

Как считается слово: текст раскладывается по «звучащему» времени (паузы пропускаются)
пропорционально числу букв, при этом концы предложений притягиваются к ближайшей паузе.
Точность обычно ±0,2–0,4 с; начало фразы после паузы — точное.
"""
import argparse, json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def speech_segments(path, noise=-35, min_sil=0.25, min_seg=0.12):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-vn", "-af",
                        f"silencedetect=n={noise}dB:d={min_sil}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    T = duration(path)
    sil = list(zip(starts, ends + [T] * (len(starts) - len(ends))))
    segs, t = [], 0.0
    for s0, s1 in sil:
        if s0 - t >= min_seg:
            segs.append([max(0.0, t), s0])
        t = s1
    if T - t >= min_seg:
        segs.append([t, T])
    return segs, T


def waveform(path, T, px_per_s=120):
    w = max(400, int(T * px_per_s))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if not len(a):
        return np.zeros(w)
    n = len(a) // w or 1
    return np.abs(a[: n * w]).reshape(-1, n).max(1)


def words_timeline(text, segs):
    """Каждому слову — оценка времени начала."""
    words = re.findall(r"\S+", text)
    if not words or not segs:
        return []
    total = sum(e - s for s, e in segs)
    weights = [len(re.sub(r"[^\w$%]", "", w)) + 1 for w in words]
    cum = np.cumsum([0] + weights[:-1]) / sum(weights)

    def at(frac):                                   # доля звучащего времени -> абсолютное время
        x = frac * total
        for s, e in segs:
            if x <= e - s:
                return s + x
            x -= e - s
        return segs[-1][1]
    times = [at(c) for c in cum]
    # притягиваем начало слова после конца предложения к ближайшему началу сегмента
    starts = [s for s, _ in segs]
    for i in range(1, len(words)):
        if re.search(r"[.!?…:;]$", words[i - 1]):
            j = int(np.argmin([abs(s - times[i]) for s in starts]))
            if abs(starts[j] - times[i]) < 1.2:
                delta = starts[j] - times[i]
                for k in range(i, len(words)):          # сдвигаем хвост, не ломая порядок
                    times[k] += delta * max(0.0, 1 - (times[k] - times[i]) / 4)
    return list(zip(words, times))


def find(word_times, query):
    q = [w.lower() for w in re.findall(r"\w+", query)]
    norm = [re.sub(r"[^\w]", "", w).lower() for w, _ in word_times]
    for i in range(len(norm) - len(q) + 1):
        if all(norm[i + j].startswith(q[j][: max(3, len(q[j]) - 2)]) for j in range(len(q))):
            return word_times[i][1]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--text", help="файл с текстом закадра (или сам текст)")
    ap.add_argument("--find", nargs="*", default=[])
    ap.add_argument("--noise", type=float, default=-35, help="порог тишины, дБ (шумная запись: -30)")
    ap.add_argument("--min-silence", type=float, default=0.25, help="мин. пауза, с")
    a = ap.parse_args()

    segs, T = speech_segments(a.audio, a.noise, a.min_silence)
    print(f"Длительность {T:.2f} с, фраз (между паузами): {len(segs)}")
    for i, (s, e) in enumerate(segs, 1):
        print(f"  {i:2d}. {s:6.2f} – {e:6.2f}  ({e - s:4.2f} с)")

    text = None
    if a.text:
        text = open(a.text, encoding="utf-8").read() if os.path.exists(a.text) else a.text
    wt = words_timeline(text, segs) if text else []
    found = {}
    for q in a.find:
        t = find(wt, q) if wt else None
        found[q] = t
        print(f"  «{q}»: {'≈ %.2f с' % t if t is not None else 'не найдено в тексте'}")

    stem = os.path.splitext(a.audio)[0]
    json.dump({"duration": T, "phrases": segs, "words": [[w, round(t, 2)] for w, t in wt], "find": found},
              open(stem + "_timing.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # картинка для проверки
    wav = waveform(a.audio, T)
    Wd, Hd = len(wav), 260
    im = Image.new("RGB", (Wd, Hd), (250, 250, 250)); d = ImageDraw.Draw(im)
    f = ImageFont.truetype(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "inter", "Inter-Regular.otf"), 13)
    for s, e in segs:
        d.rectangle([s / T * Wd, 0, e / T * Wd, Hd], fill=(226, 236, 250))
    mx = wav.max() or 1
    for x, v in enumerate(wav):
        h = v / mx * 100
        d.line([x, 130 - h, x, 130 + h], fill=(70, 80, 120))
    for sec in range(int(T) + 1):
        x = sec / T * Wd
        d.line([x, Hd - 20, x, Hd], fill=(150, 150, 150)); d.text((x + 2, Hd - 18), f"{sec}s", fill=(90, 90, 90), font=f)
    for i, (s, _) in enumerate(segs, 1):
        x = s / T * Wd; d.line([x, 0, x, Hd - 22], fill=(40, 110, 220), width=2); d.text((x + 3, 2), f"{i}: {s:.2f}", fill=(40, 110, 220), font=f)
    for q, t in found.items():
        if t is not None:
            x = t / T * Wd; d.line([x, 30, x, Hd - 22], fill=(220, 40, 60), width=2); d.text((x + 3, 32), f"{q} {t:.2f}", fill=(220, 40, 60), font=f)
    im.save(stem + "_wave.png")
    print("->", stem + "_timing.json", "|", stem + "_wave.png")


if __name__ == "__main__":
    main()
