# Фабрика вставок для YouTube

Анимированные вставки для монтажа в CapCut (4K, 30 fps):
- скриншот статьи → выделение фразы → замена на русский перевод;
- списки и рейтинги с выделениями по таймкодам и лицами-стикерами;
- горизонтальные (16:9) и вертикальные для Shorts (9:16), на фирменных фонах или на хромакее.

Скрипты запускает Claude Code: ты присылаешь скриншот и пишешь, что выделить, — он делает всё сам
по правилам из `CLAUDE.md`. Руками запускать тоже можно (команды ниже).

---

## 1. Установка на Mac (один раз)

Все команды — в приложении **Терминал** (Finder → Программы → Утилиты → Терминал).
Вставляй по одной, жди окончания, потом следующую.

### 1.1. Homebrew — менеджер программ для Mac

Проверь, есть ли он:

```bash
brew --version
```

Если пишет `command not found` — установи (попросит пароль от Mac, при вводе символы не видны — это нормально):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

В конце установщик напишет **Next steps** с двумя командами — выполни их. На Mac с Apple Silicon (M1/M2/M3/M4) это:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
```

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

### 1.2. Git, Python и ffmpeg

```bash
brew install git python ffmpeg
```

Проверка (каждая должна напечатать версию):

```bash
git --version && python3 --version && ffmpeg -version | head -1
```

### 1.3. Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

После установки закрой и снова открой Терминал, затем:

```bash
claude --version
```

При первом запуске `claude` попросит войти в аккаунт Claude — войди тем же аккаунтом.
Актуальная инструкция по установке: https://code.claude.com/docs

---

## 2. Скачать репозиторий

Положим его в папку `Projects` в домашней папке (можно любую другую — главное потом запускать
всё из неё).

```bash
mkdir -p ~/Projects
```

```bash
cd ~/Projects
```

```bash
git clone https://github.com/Dimmvvv/Claude.git motion
```

Появится папка `~/Projects/motion` — это и есть репозиторий. Дальше **все команды выполняются
из неё**:

```bash
cd ~/Projects/motion
```

> Если репозиторий уже приватный: сначала `brew install gh`, потом `gh auth login` (выбрать
> GitHub.com → HTTPS → Login with a web browser), и вместо `git clone …` — `gh repo clone Dimmvvv/Claude motion`.

---

## 3. Библиотеки Python (внутри папки репозитория)

Ставим не «в систему», а в отдельную папку `.venv` **внутри репозитория** — так ничего на Mac не
ломается, а в git она не попадает.

```bash
cd ~/Projects/motion
```

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

`source .venv/bin/activate` нужно повторять **каждый раз**, когда открываешь новый Терминал для
работы со скриптами (в начале строки появится `(.venv)`). Claude Code делает это сам, если ему
сказать — правило записано в `CLAUDE.md`.

---

## 4. Фирменные шрифты (вручную, в папку репозитория)

Пока репозиторий публичный, файлы шрифтов в git не хранятся. Положи три файла в папку
`brand/fonts/` внутри репозитория **ровно с такими именами**:

| Файл | Что это |
|---|---|
| `brand/fonts/Gilroy-Regular.ttf` | Gilroy Regular — плашка, подпись «ИСТОЧНИК» |
| `brand/fonts/Gilroy-MediumItalic.ttf` | Gilroy Medium Italic |
| `brand/fonts/CDOvuer-Regular.otf` | CD Ovuer — заголовки-перебивки |

Открыть папку в Finder:

```bash
open brand/fonts
```

(если папки нет: `mkdir -p brand/fonts` и снова `open brand/fonts`). Без этих файлов всё работает,
просто вместо Gilroy будет похожий запасной шрифт.

⚠️ CD Ovuer в архиве — версия PERSONAL USE: для монетизируемого канала нужна коммерческая лицензия.

Шрифты для переводов (13 семейств с кириллицей) и Inter уже лежат в `insert_maker/fonts/` — ставить
ничего не нужно.

---

## 5. Проверка

```bash
cd ~/Projects/motion && source .venv/bin/activate && python3 check_setup.py
```

Должны быть ✅ у Python, numpy, Pillow, ffmpeg, git и строка «пробный кадр отрисован». Картинку можно
посмотреть: `open insert_maker/work/check_setup.png`. Если где-то ❌ — под ним написано, что сделать.

---

## 6. Как работать

### Через Claude (основной способ)

```bash
cd ~/Projects/motion && claude
```

Пиши как в чате: «вот скриншот, выдели второй абзац и переведи, источник THR», «то же для шортса»,
«на красном фоне», «плашка „Друзья“», «на хромакее». Большие скриншоты и записи экрана — в `.zip`.
Готовые видео появляются в `insert_maker/work/` (открыть: `open insert_maker/work`).

Модель: для обычных вставок по шаблону хватает **Sonnet**; для новых сложных анимаций — **Opus**
(`/model` в Claude Code).

### Руками (если нужно)

Из папки `insert_maker` (с активированным `.venv`):

```bash
cd ~/Projects/motion/insert_maker
```

```bash
python3 make_insert.py work/shot.png --detect
```

```bash
python3 make_insert.py work/shot.png --sel 3:1-6:-1 --ru 'Перевод…' --source 'Издание' --preview
```

```bash
python3 make_insert.py work/shot.png --sel 3:1-6:-1 --ru 'Перевод…' --source 'Издание' --out work/name.mp4
```

Все опции — `python3 make_insert.py --help` и `insert_maker/README.md`.

### Обновить репозиторий (если что-то меняли в облаке или на другом компьютере)

```bash
cd ~/Projects/motion && git pull
```

---

## 7. Что где лежит

| Путь | Что там | В git |
|---|---|---|
| `CLAUDE.md` | инструкции для Claude: как делать вставки, правила проверки | да |
| `insert_maker/make_insert.py` | скриншот → выделение → перевод | да |
| `insert_maker/make_ranking.py` | список/рейтинг с таймкодами и лицами (сцена в JSON) | да |
| `insert_maker/motion.py` | все параметры движения (длительности, кривые, пружина) | да |
| `insert_maker/tools/phrases.py` | тайминги фраз из записи голоса | да |
| `insert_maker/fonts/` | шрифты для переводов + Inter (свободные лицензии) | да |
| `insert_maker/examples/` | примеры | да |
| `insert_maker/work/` | твои скриншоты, фото, готовые видео | **нет** |
| `brand/` | палитра, фоны (5 цветов, с плашкой и без), макеты | да |
| `brand/fonts/` | Gilroy, CD Ovuer — кладёшь сам | **нет** |
| `references/STYLE.md`, `SHORTS.md` | стиль анимаций из референсов | да |
| `.venv/` | библиотеки Python | **нет** |
| `requirements.txt`, `check_setup.py` | список библиотек, проверка установки | да |

---

## 8. Если что-то не так

| Проблема | Что сделать |
|---|---|
| `command not found: brew` | выполни две команды из шага 1.1 (Next steps) или перезапусти Терминал |
| `externally-managed-environment` при `pip install` | ты не активировал `.venv`: `source .venv/bin/activate` |
| `ModuleNotFoundError: numpy / PIL` | то же: активируй `.venv`, затем `pip install -r requirements.txt` |
| `ffmpeg: command not found` | `brew install ffmpeg` |
| Рендер очень медленный / Mac греется | нормально для 4K на MacBook Air; для проверки используй `--preview`, финал — одним рендером |
| `git pull` пишет про конфликт | не правь одни и те же файлы одновременно здесь и в облаке; пришли текст ошибки Claude |
| Вместо Gilroy другой шрифт | проверь имена файлов в `brand/fonts/` (таблица в шаге 4) |
