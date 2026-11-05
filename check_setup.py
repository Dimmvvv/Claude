#!/usr/bin/env python3
"""Проверка установки: python3 check_setup.py (из корня репозитория, с активированным .venv)."""
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ok = True


def line(good, text, hint=""):
    global ok
    ok &= good or hint.startswith("(необязательно)")
    print(("  ✅ " if good else "  ❌ ") + text + ("" if good or not hint else f"\n       → {hint}"))


print("Проверка окружения для вставок\n")
line(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]}", "нужен Python 3.9+: brew install python")
try:
    import numpy; line(True, f"numpy {numpy.__version__}")
except ImportError:
    line(False, "numpy", "source .venv/bin/activate && pip install -r requirements.txt")
try:
    import PIL; line(True, f"Pillow {PIL.__version__}")
except ImportError:
    line(False, "Pillow", "source .venv/bin/activate && pip install -r requirements.txt")
for tool in ("ffmpeg", "ffprobe"):
    line(shutil.which(tool) is not None, tool, "brew install ffmpeg")
line(shutil.which("git") is not None, "git", "brew install git")
line(shutil.which("claude") is not None, "Claude Code (claude)",
     "(необязательно) curl -fsSL https://claude.ai/install.sh | bash")

fonts = os.path.join(ROOT, "brand", "fonts")
for f in ("Gilroy-Regular.ttf", "Gilroy-MediumItalic.ttf", "CDOvuer-Regular.otf"):
    line(os.path.exists(os.path.join(fonts, f)), f"brand/fonts/{f}",
         "(необязательно) без него — запасной шрифт; положи файл в brand/fonts/ с таким именем")

# пробный рендер одного кадра
if ok:
    try:
        sys.path.insert(0, os.path.join(ROOT, "insert_maker"))
        import make_insert as mi
        from argparse import Namespace
        a = Namespace(image=os.path.join(ROOT, "insert_maker", "examples", "adweek.png"), sel=["7:5-7:-1"],
                      ru=["Проверка установки."], source="Проверка", bg="blue", title=None, duration=7.0, fps=30,
                      card_w=None, hl_time=0.9, pause=0.9, ru_time=1.2, dim=0.62, blur=1.3, font="serif",
                      intro="fade", format="long", motion="ease")
        frame = mi.build(a)[0]
        out = os.path.join(ROOT, "insert_maker", "work"); os.makedirs(out, exist_ok=True)
        p = os.path.join(out, "check_setup.png"); frame(6.9).resize((1920, 1080)).save(p)
        line(True, f"пробный кадр отрисован: insert_maker/work/check_setup.png")
    except Exception as e:  # noqa: BLE001
        line(False, f"пробный кадр: {e}", "пришли этот текст ошибки в чат Claude")

print("\nГотово, можно работать." if ok else "\nЕсть что поправить — см. ❌ выше.")
sys.exit(0 if ok else 1)
