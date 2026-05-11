# LinkedIn Auto-Poster

Публикует посты в твой личный LinkedIn-аккаунт на автопилоте.

Ты вводишь тему — например, *"ускорение инференса трансформеров на проде"* — а дальше всё само:
1. **Gemini 3.1 Flash Lite** исследует тему через встроенный Google Search
2. Пишет отформатированный пост на английском с хэштегами
3. **Gemini 3.1 Flash Image** генерирует тематическую картинку
4. Всё публикуется в твой LinkedIn через официальный API

Есть два способа работы: **веб-интерфейс** (удобно) и **CLI** (для скриптов и автоматизации).

---

## Содержание

- [Что нужно](#что-нужно)
- [Быстрый старт](#быстрый-старт)
- [Получить LinkedIn токен](#получить-linkedin-токен)
- [Веб-интерфейс](#веб-интерфейс)
- [CLI](#cli)
- [Структура проекта](#структура-проекта)
- [API эндпоинты](#api-эндпоинты)
- [Настройки .env](#настройки-env)

---

## Что нужно

| Требование | Где взять |
|---|---|
| Python 3.11+ | [python.org](https://python.org) |
| Google AI API ключ | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — бесплатный tier |
| LinkedIn аккаунт + Developer App | [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) |

> **Важно про LinkedIn App:** при создании приложения потребуется привязать LinkedIn Page. Достаточно создать любую страницу — она нужна только как формальная привязка, в постах не фигурирует. В разделе **Products** добавь: *Sign In with LinkedIn using OpenID Connect* и *Share on LinkedIn*.

---

## Быстрый старт

```bash
# 1. Клонируй репозиторий
git clone <repo-url>
cd LinkedIn

# 2. Создай виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Установи зависимости
pip install -r backend/requirements.txt

# 4. Заполни переменные окружения
cp .env.example .env
# Открой .env и заполни значения (см. раздел «Настройки .env»)

# 5. Получи LinkedIn токен (один раз)
python -m backend.auth

# 6. Запусти сервер
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

Открой [http://localhost:8000](http://localhost:8000) — готово.

---

## Получить LinkedIn токен

Это нужно сделать **один раз**. Токен живёт 60 дней, потом повторить.

```bash
python -m backend.auth
```

Скрипт откроет браузер → залогинься в LinkedIn → подтверди доступ для приложения.  
Токен и Person URN автоматически запишутся в `.env`.

> **Если логин только через Apple ID:** открой [linkedin.com](https://www.linkedin.com) в Safari, залогинься через Apple, и только потом запускай `python -m backend.auth` — браузер подхватит активную сессию.

> **Если ошибка `redirect_uri does not match`:** зайди в настройки LinkedIn App → вкладка **Auth** → **Authorized redirect URLs** → добавь `http://localhost:8080/callback`.

---

## Веб-интерфейс

После запуска сервера открой [http://localhost:8000](http://localhost:8000).

```
┌─────────────────────────┬──────────────────────────────┐
│  1. Тема                │  2. Пост и промпт            │
│                         │                              │
│  [textarea: тема]       │  [textarea: текст поста]     │
│                         │                              │
│  ☐ Dry-run              │  [textarea: промпт картинки] │
│  ☐ Без картинки         │                              │
│                         │  [Опубликовать в LinkedIn]   │
│  [Только текст]         │                              │
│  [Запустить сценарий]   │                              │
└─────────────────────────┴──────────────────────────────┘
│  Лог                                                   │
└────────────────────────────────────────────────────────┘
```

**Кнопки:**

| Кнопка | Что делает |
|---|---|
| **Только текст** | Генерирует пост и промпт картинки, не публикует и не рисует картинку |
| **Запустить сценарий** | Полный цикл: текст → картинка → публикация (или dry-run) |
| **Опубликовать в LinkedIn** | Публикует то, что сейчас в полях — можно отредактировать перед отправкой |

**Типичный флоу:**
1. Введи тему → нажми **Только текст**
2. Прочитай пост, подредактируй если нужно
3. Нажми **Опубликовать в LinkedIn**

---

## CLI

Для запуска без браузера:

```bash
# Полный сценарий: генерация + картинка + публикация
python -m backend.main_cli "ускорение инференса трансформеров на проде"

# Сгенерировать и показать пост, но НЕ публиковать
python -m backend.main_cli --dry-run "квантизация LLM"

# Без картинки (только текст)
python -m backend.main_cli --no-image "оптимизация батч-обработки"

# Интерактивный ввод темы
python -m backend.main_cli
```

---

## Структура проекта

```
LinkedIn/
├── .env.example             # шаблон переменных окружения
├── .env                     # твои ключи (не коммитить!)
├── requirements.txt         # ссылается на backend/requirements.txt
│
├── backend/
│   ├── app.py               # FastAPI-сервер, все /api/* эндпоинты
│   ├── auth.py              # OAuth 2.0 flow для получения LinkedIn токена
│   ├── generator.py         # Gemini 3.1 Flash Lite + Google Search → пост
│   ├── images.py            # Gemini 3.1 Flash Image → картинка
│   ├── linkedin.py          # LinkedIn API: загрузка картинки + создание поста
│   ├── main_cli.py          # CLI точка входа
│   ├── env_util.py          # проверка наличия переменных окружения
│   ├── logger.py            # настройка логирования
│   ├── proxy.py             # SOCKS5 прокси для всех HTTP-клиентов
│   ├── paths.py             # пути к директориям
│   ├── generated_images/    # сюда сохраняются сгенерированные картинки
│   └── requirements.txt     # зависимости Python
│
└── frontend/
    ├── index.html           # SPA (раздаётся FastAPI)
    └── assets/
        ├── app.js           # логика интерфейса
        └── styles.css       # стили
```

---

## API эндпоинты

Сервер поднимается на `http://localhost:8000`. Документация Swagger: [/docs](http://localhost:8000/docs).

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/health` | Проверка работоспособности сервера |
| `GET` | `/api/env` | Статус заполненности `.env` |
| `POST` | `/api/generate` | Только генерация текста поста (без картинки и LinkedIn) |
| `POST` | `/api/run` | Полный сценарий: текст → картинка → публикация |
| `POST` | `/api/publish` | Опубликовать готовый текст (картинка генерируется по промпту) |

**Пример: только текст**
```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"topic": "transformer inference optimization"}'
```

**Пример: полный сценарий в dry-run**
```bash
curl -X POST http://localhost:8000/api/run \
  -H "Content-Type: application/json" \
  -d '{"topic": "vLLM PagedAttention", "dry_run": true, "no_image": false, "aspect_ratio": "16:9"}'
```

---

## Настройки .env

Скопируй `.env.example` → `.env` и заполни:

```env
# ── SOCKS5 прокси (опционально) ─────────────────────────
# Формат: socks5://user:password@host:port
SOCKS5_PROXY=

# ── LinkedIn ─────────────────────────────────────────────
# Получить на: https://www.linkedin.com/developers/apps
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=

# Заполняется автоматически после: python -m backend.auth
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_PERSON_URN=

# ── Google AI (Gemini + картинки) ────────────────────────
# Получить на: https://aistudio.google.com/app/apikey
GOOGLE_API_KEY=
```

> Файл `.env` содержит секреты — он уже добавлен в `.gitignore`.

---

## Для разработчика

**Запуск с hot-reload:**
```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

**Логи** пишутся в stderr в формате `HH:MM:SS [LEVEL] module — message`.  
Уровень по умолчанию — `DEBUG` (видно сырые ответы Gemini).

**Добавить новую модель для текста или картинки:**
- Текст: `backend/generator.py` → строка `model="gemini-3.1-flash-lite"`
- Картинка: `backend/images.py` → константа `IMAGE_MODEL`

**Доступные Google AI модели** (актуальный список):
```bash
python -c "
from google import genai
import os; from dotenv import load_dotenv; load_dotenv()
c = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
for m in c.models.list(): print(m.name)
"
```
