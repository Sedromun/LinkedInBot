# LinkedIn Auto-Poster

Многопользовательский Telegram-бот, который автоматически генерирует и публикует посты в LinkedIn.

Пользователь регистрируется в боте, привязывает свой LinkedIn-аккаунт, выбирает темы, которые ему интересны. Каждый день в 18:00 бот предлагает сгенерировать пост. За $1 (списывается с внутреннего баланса) Gemini исследует тему через Google Search, пишет грамотный LinkedIn-пост и рисует к нему картинку, после чего публикует от имени пользователя.

---

## Содержание

1. [Что под капотом](#что-под-капотом)
2. [Архитектура](#архитектура)
3. [Два режима — DEV и PROD](#два-режима--dev-и-prod)
4. [Быстрый старт (DEV)](#быстрый-старт-dev)
5. [Деплой в PROD](#деплой-в-prod)
6. [Конфигурация: все переменные .env](#конфигурация-все-переменные-env)
7. [Команды бота](#команды-бота)
8. [Пользовательский флоу](#пользовательский-флоу)
9. [Биллинг](#биллинг)
10. [Отказоустойчивость](#отказоустойчивость)
11. [Уведомления и настройки](#уведомления-и-настройки)
12. [API эндпоинты](#api-эндпоинты)
13. [Схема базы данных](#схема-базы-данных)
14. [Миграции БД](#миграции-бд)
15. [Структура проекта и модули](#структура-проекта-и-модули)
16. [Мониторинг и логи](#мониторинг-и-логи)
17. [Расширение](#расширение)
18. [Troubleshooting](#troubleshooting)
19. [Security-чеклист для PROD](#security-чеклист-для-prod)
20. [Известные ограничения / TODO](#известные-ограничения--todo)

---

## Что под капотом

| Слой | Технология |
|---|---|
| Telegram bot | [aiogram v3](https://docs.aiogram.dev) (async) |
| Web / OAuth callback | [FastAPI](https://fastapi.tiangolo.com) + uvicorn |
| LLM (текст + дизайн инфографик) | Gemini 3.1 Flash Lite (primary) → fallback на 5 моделей |
| Картинки (инфографика) | **OpenAI `gpt-image-2`** → fallback на gpt-image-1 → nano-banana |
| Web search | Google Search (Gemini) / Bing (OpenAI Responses API) |
| LinkedIn API | `/v2/ugcPosts` + `/v2/assets` (OAuth 2.0, multi-image) |
| Хранилище | SQLite (DEV) / Postgres 16 (PROD), SQLAlchemy 2.0 async |
| Миграции | Alembic |
| Шедулер | APScheduler (`AsyncIOScheduler`) — per-user cron |
| Контейнеризация | Docker + docker compose |
| Конфиг | pydantic-settings |

### Почему так

**Gemini** хорош в reasoning + встроенный Google Search → пишет пост на актуальных данных и **сам дизайнит** ТЗ на инфографик-слайды (заголовки, лейблы, цифры).

**OpenAI gpt-image-1/2** — единственные image-модели, которые корректно рисуют **читаемый текст внутри картинки** (заголовки слайдов, лейблы карточек, метрики). Это критично — наши картинки не декор, а слайды с информацией.

**Fallback-цепочки**: если основная модель упала (503/overload), автоматически пробуется следующая. См. [Отказоустойчивость](#отказоустойчивость).

Pipeline для одного поста:
```
тема → Gemini (с web search) ─┬─ текст поста
                              └─ N image_prompts ─→ gpt-image-2 × N → инфографики
                                                    (параллельно через asyncio.gather)
```

---

## Архитектура

```
┌─────────────┐     /start, /generate     ┌──────────────┐
│  Пользова-  │  ──────────────────────►  │  Telegram    │
│  тель       │  ◄──────────────────────  │  Bot (bot)   │  ← aiogram
└─────────────┘                           └──────┬───────┘
                                                 │ async
                                                 ▼
                            ┌─────────────────────────────────┐
                            │  Services (oauth/billing/post)  │
                            └──────┬──────────────────────────┘
                                   │
                ┌──────────────────┼──────────────────────┐
                ▼                  ▼                      ▼
        ┌──────────────┐   ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
        │  Postgres /  │   │ Gemini 3.1     │   │ OpenAI         │   │ LinkedIn API   │
        │   SQLite     │   │ + Google Search│   │ gpt-image-1    │   │ (OAuth + post) │
        │              │   │ (текст +       │   │ (инфографики)  │   └────────────────┘
        │  users       │   │  image prompts)│   └────────────────┘
        │  generations │   └────────────────┘
        │  payments    │
        └──────────────┘
                ▲
                │
        ┌──────────────┐    HTTP /oauth/callback?state=…
        │  FastAPI     │  ◄───────  LinkedIn  ◄── юзер кликает Allow
        │  (api)       │
        │  + /admin    │
        └──────────────┘

      ┌─────────────────┐
      │  APScheduler    │  Каждый день в 18:00 → daily nudge всем юзерам
      └─────────────────┘
```

Два контейнера работают одновременно, общая БД:

| Контейнер | Команда | Зачем |
|---|---|---|
| `api` | `uvicorn backend.app:app` | OAuth callback от LinkedIn + healthcheck + админ-метрики |
| `bot` | `python -m backend.bot.main` | Telegram long-polling + scheduler ежедневных напоминаний |

---

## Два режима — DEV и PROD

### 🧪 DEV (`MOCK_LINKEDIN=true`)

- LinkedIn API **не дёргается вообще**
- Привязка моментальная с fake-токеном
- Публикация — только запись в БД, post_id вида `mock-42-3819`
- БД — SQLite (файл `backend/data/app.db`)
- Gemini и картинки работают **по-настоящему** — можно проверить весь pipeline

Из секретов нужны только: `GOOGLE_API_KEY` + `TELEGRAM_BOT_TOKEN`.

### 🚀 PROD (`MOCK_LINKEDIN=false`)

- Реальный LinkedIn OAuth flow
- Реальная публикация постов через `/v2/ugcPosts`
- БД — Postgres (отдельный контейнер с volume)
- Нужен сервер с публичным IP (LinkedIn должен достучаться до `/oauth/callback`)

---

## Быстрый старт (DEV)

```bash
git clone <repo-url> && cd LinkedIn
cp .env.example .env
```

Заполни в `.env`:
```env
MOCK_LINKEDIN=true
GOOGLE_API_KEY=AIza...              # https://aistudio.google.com/app/apikey
OPENAI_API_KEY=sk-...               # https://platform.openai.com/api-keys (нужен Billing)
TELEGRAM_BOT_TOKEN=12345:abc...     # @BotFather → /newbot
```

Запусти:
```bash
docker compose -f docker-compose.dev.yml up --build
```

Найди бота в Telegram → `/start`.

> При первом запуске docker скачает `python:3.12-slim` и поставит зависимости (~3-5 минут). Последующие запуски — секунды.

---

## Деплой в PROD

### Шаг 1 — Подготовка LinkedIn App

1. [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) → создай app или открой существующий
2. Привяжи Company Page (можно создать пустую — она нужна только формально)
3. На вкладке **Products** добавь:
   - **Sign In with LinkedIn using OpenID Connect**
   - **Share on LinkedIn**
4. На вкладке **Auth**:
   - Скопируй **Client ID** и **Client Secret** → в `.env`
   - В **Authorized redirect URLs** добавь: `http://your-server-ip:8000/oauth/callback`

### Шаг 2 — Сервер

На VPS / выделенном сервере с публичным IP:

```bash
git clone <repo-url> && cd LinkedIn
cp .env.example .env
nano .env
```

Заполни в `.env`:
```env
MOCK_LINKEDIN=false
PUBLIC_BASE_URL=http://1.2.3.4:8000     # ровно то же что в LinkedIn App
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
GOOGLE_API_KEY=...
TELEGRAM_BOT_TOKEN=...
POSTGRES_PASSWORD=$(openssl rand -base64 32)   # сильный пароль для БД
```

Запусти:
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Проверь:
```bash
curl http://localhost:8000/api/health                           # → {"status":"ok"}
docker compose -f docker-compose.prod.yml logs -f bot           # бот должен сказать "Бот запускается..."
```

### Шаг 3 — HTTPS (опционально, но рекомендуется)

LinkedIn принимает HTTP-redirect только для тестовых апп. Для прод-доступа сделай HTTPS:

1. Купи домен → направь A-запись на IP сервера
2. Поставь nginx или caddy впереди docker-сервиса (port 443 → port 8000)
3. Обнови `PUBLIC_BASE_URL=https://your-domain.com` в `.env`
4. Обнови redirect URL в LinkedIn App

---

## Конфигурация: все переменные .env

| Переменная | DEV | PROD | Описание |
|---|---|---|---|
| `MOCK_LINKEDIN` | `true` | `false` | Включает mock-режим |
| `GOOGLE_API_KEY` | ✅ | ✅ | [aistudio.google.com](https://aistudio.google.com/app/apikey) — Gemini для текста |
| `OPENAI_API_KEY` | ✅ | ✅ | [platform.openai.com](https://platform.openai.com/api-keys) — картинки + fallback для текста |
| `IMAGE_QUALITY` | `medium` | `medium` | `low` ($0.011) / `medium` ($0.04) / `high` ($0.17) за картинку |
| `MAX_IMAGES_PER_POST` | `2` | `2` | Верхняя граница картинок на пост (1-4) |
| `TELEGRAM_BOT_TOKEN` | ✅ | ✅ | [@BotFather](https://t.me/BotFather) → /newbot |
| `LINKEDIN_CLIENT_ID` | — | ✅ | LinkedIn App → Auth |
| `LINKEDIN_CLIENT_SECRET` | — | ✅ | LinkedIn App → Auth |
| `PUBLIC_BASE_URL` | — | ✅ | Например `http://1.2.3.4:8000` |
| `POSTGRES_PASSWORD` | — | ✅ | `openssl rand -base64 32` |
| `COST_PER_POST_CENTS` | `100` | `100` | Цена за пост (100 = $1.00) |
| `REGEN_TEXT_CENTS` | `50` | `50` | Цена перегенерации текста (50 = $0.50) |
| `INITIAL_BALANCE_CENTS` | `300` | `300` | Бонус новому юзеру (300 = $3.00) |
| `SOCKS5_PROXY` | — | — | Например `socks5://user:pass@host:1080` (опционально) |
| `DATABASE_URL` | автоматом | автоматом | Compose переопределяет — не трогай |

> Время напоминаний больше **не задаётся через .env** — каждый юзер выбирает сам через `/settings` (хранится в БД: `users.notification_time` и `users.notification_days_json`).

> При запуске через `docker compose` переменные `MOCK_LINKEDIN` и `DATABASE_URL` **переопределяются на уровне compose** — менять их в `.env` бесполезно.

---

## Команды бота

| Команда | Что делает | Состояние |
|---|---|---|
| `/start` | Регистрация (если новый) + главное меню с инлайн-кнопками | Любое |
| `/generate` | Запросить тему → запустить pipeline → опубликовать | Авторизован |
| `/interests` | Мультивыбор из 12 категорий через инлайн-чекбоксы | Любое |
| `/balance` | Показать баланс, кнопка пополнения | Любое |
| `/settings` | Текущие настройки (напоминания, интересы) | Любое |
| `/notifications` | Тогл вкл/выкл ежедневных напоминаний | Любое |
| `/help` | Список команд | Любое |
| `/cancel` | Сбросить ввод (например, если передумал вводить тему) | FSM-состояние |

### Категории интересов (`backend/services/interests.py`)

| Slug | Label |
|---|---|
| `ai_agents` | 🤖 AI Agents & Multi-agent systems |
| `llm` | 🧠 LLMs & Foundation Models |
| `ml_ops` | 📊 Machine Learning / MLOps |
| `ai_infra` | ⚡ AI Infrastructure (GPU, inference) |
| `robotics` | 🦾 Robotics & Embodied AI |
| `crypto` | ₿ Crypto & Web3 |
| `defi` | 💸 DeFi & Tokenomics |
| `cybersec` | 🛡 Cybersecurity |
| `devtools` | 🛠 Developer Tools & DX |
| `cloud` | ☁️ Cloud & DevOps |
| `data_eng` | 🗄 Data Engineering |
| `startups` | 🚀 Startups & VC |

---

## Пользовательский флоу

### Регистрация и привязка LinkedIn

```
/start
  ├─ если новый юзер: создаём User, начисляем $3 стартового баланса
  ├─ если LinkedIn привязан: показываем welcome для авторизованного
  └─ если не привязан: показываем onboarding-инструкцию + кнопку «🔗 Connect LinkedIn»

[🔗 Connect LinkedIn]
  ├─ DEV (MOCK_LINKEDIN=true): моментально с фейк-токеном
  └─ PROD:
       1. backend выдаёт OAuth URL со state-токеном в БД
       2. юзер логинится в LinkedIn → жмёт Allow
       3. LinkedIn → /oauth/callback?code=…&state=…
       4. FastAPI обменивает code на access_token, сохраняет к юзеру в БД
       5. notify_oauth_success() → пуш в TG «✅ LinkedIn connected»
```

### Генерация поста (трёхэтапный апрув)

Юзер видит **каждый этап** и может остановить процесс / перегенерировать.

```
[✨ Generate post] или /generate
  │
  ├─ Шаг 0 — выбор темы
  │     ├─ ввести вручную  (FSM: waiting_for_topic)
  │     └─ «🎲 Pick from my interests» (FSM: confirming_auto_topic)
  │         ├─ показываем рандомную тему из интересов
  │         ├─ [✅ Yes, let's go!] → к шагу 1
  │         ├─ [🎲 Another topic]  → новая тема в том же сообщении
  │         └─ [✏️ I'll type my own] → ручной ввод
  │
  ├─ Шаг 1 — текст (Phase 1, БЕЗ списания)
  │     ├─ generate_text() → Gemini + web search → post + image_prompts
  │     ├─ показываем юзеру полный текст
  │     └─ FSM: reviewing_text
  │         ├─ [🎨 Generate images]              → к шагу 2
  │         ├─ [🔄 Regenerate text (−$0.50)]     → списываем $0.50, повторяем шаг 1
  │         └─ [❌ Cancel]                        → выход (0 списано)
  │
  ├─ Шаг 2 — картинки (Phase 2, БЕЗ списания)
  │     ├─ generate_images() — параллельно N штук через gpt-image-2
  │     └─ если все упали, продолжаем без картинок
  │
  ├─ Шаг 3 — финальный апрув
  │     ├─ шлём картинки (photo / media_group) + текст
  │     └─ FSM: reviewing_full_post
  │         ├─ [🚀 Publish to LinkedIn]  → к шагу 4
  │         └─ [❌ Cancel]                 → выход (0 списано)
  │
  └─ Шаг 4 — публикация (Phase 3, СПИСАНИЕ $1)
        ├─ проверяем balance ≥ $1
        ├─ DEV: возвращаем mock-post_id
        ├─ PROD: LinkedInClient.publish() → post_id
        ├─ списываем $1 → пишем Generation(status=PUBLISHED)
        └─ шлём «🚀 Published!» со ссылкой на LinkedIn-пост
```

### Ежедневные напоминания (per-user расписание)

Юзер сам выбирает **во сколько** и **в какие дни** хочет напоминания через `/settings`.

```
APScheduler tick (каждую минуту в :00 секунд):
  current_time  = "HH:MM" (локальное время сервера)
  current_wday  = 0..6 (Mon..Sun)

  → users where:
       daily_notifications == True
       AND linkedin_access_token IS NOT NULL
       AND notification_time == current_time
       AND current_wday IN notification_days
       AND balance_cents >= COST_PER_POST_CENTS
  → send_daily_nudge() каждому
```

---

## Биллинг

| Параметр | Дефолт | Где меняется |
|---|---|---|
| Цена за пост (текст+картинки+публикация) | $1.00 | `.env` → `COST_PER_POST_CENTS=100` |
| Перегенерация текста (только текст) | $0.50 | `.env` → `REGEN_TEXT_CENTS=50` |
| Стартовый баланс | $3.00 | `.env` → `INITIAL_BALANCE_CENTS=300` |
| Способ оплаты | Mock | `backend/services/billing_service.py::topup_mock` |
| Хранение | `users.balance_cents` (int) | точность до цента |

### Правила списания

1. **Основная сумма ($1) списывается только в Phase 3 — при подтверждении публикации.**
   Юзер может отменить на любом из трёх шагов (текст / картинки / финал) — ничего не спишется.
2. **Перегенерация текста ($0.50)** списывается мгновенно при нажатии кнопки «🔄 Regenerate text».
   Если на это не хватает баланса — кнопка молча алерт-сообщение, генерация не запускается.
3. Если pipeline упал на этапе публикации (LinkedIn API упал) — деньги не уходят,
   в БД остаётся `Generation(status=FAILED, error=…)`.
4. Юзер с балансом меньше $1 получает `InsufficientFunds` при попытке публикации.

### Mock-пополнение

Кнопки `[$5] [$10] [$25]` в `/balance`. Деньги падают на баланс **моментально**, без реального платежа. В таблице `payments` создаётся запись `method='mock', status='completed'`.

### Прикручиваем реальный платёж (Stripe / ЮKassa)

1. Замени `topup_mock()` → создай pending Payment + сгенерь Stripe/ЮKassa URL
2. Добавь FastAPI webhook `/webhooks/stripe` → обнови Payment → credit_balance
3. В UI бота кнопка `[Пополнить]` теперь должна слать Stripe-ссылку, а не моментально начислять

---

## Отказоустойчивость

### Fallback-цепочки моделей

Если основная модель упала с **503 / UNAVAILABLE / overload / high demand / 404** — pipeline **молча переходит к следующей** в цепочке. Любая другая ошибка (неверный ключ, quota, сеть) — пробрасывается сразу.

**Текст** (`backend/generator.py::TEXT_MODEL_CHAIN`):

| Приоритет | Провайдер | Модель | Web search |
|---|---|---|---|
| 1 | Google | `gemini-3.1-flash-lite` | Google Search |
| 2 | Google | `gemini-3.1-pro-preview` | Google Search |
| 3 | Google | `gemini-3-pro-preview` | Google Search |
| 4 | OpenAI | `gpt-4.5-mini` | Bing (web_search_preview) |
| 5 | OpenAI | `gpt-5.4` | Bing |
| 6 | OpenAI | `gpt-5.5` | Bing |

OpenAI fallback использует **Responses API** с инструментом `web_search_preview` — модель тоже умеет ходить в интернет за свежими данными.

**Картинки** (`backend/images.py::IMAGE_MODEL_CHAIN`):

| Приоритет | Провайдер | Модель |
|---|---|---|
| 1 | OpenAI | `gpt-image-2` |
| 2 | OpenAI | `gpt-image-1` |
| 3 | Google | `nano-banana-pro-preview` |
| 4 | Google | `gemini-3.1-flash-image-preview` |

В логах при переключении:
```
[WARNING] backend.generator — Модель gemini/gemini-3.1-flash-lite недоступна (перегрузка), пробую следующую: 503 UNAVAILABLE
[INFO   ] backend.generator — Пробую gemini/gemini-3.1-pro-preview для темы: 'LLM inference'
[INFO   ] backend.generator — Успех: gemini/gemini-3.1-pro-preview (1456 символов поста, 2 картинки)
```

### Friendly errors для юзера

Сырые stacktrace'ы юзеру не показываются. `_friendly_error()` в `handlers.py` мапит ошибки на короткие сообщения:

| Внутренняя ошибка | Что видит юзер |
|---|---|
| `503 UNAVAILABLE` / `overload` | `All AI models are temporarily overloaded. Please try again in a few minutes.` |
| `429 / rate limit / quota` | `Rate limit reached. Please wait a moment and try again.` |
| `401 / 403 / invalid api key` | `API authentication error. Please contact support.` |
| `network / timeout / SSL` | `Network error. Please try again.` |
| LinkedIn token expired | `LinkedIn token has expired. Please reconnect via /start.` |
| Insufficient funds | `Insufficient funds. Go to /balance to top up.` |
| Прочее | `Something went wrong during generation. Please try again.` |

Полный traceback пишется в `log.exception(...)`.

### Graceful degradation для картинок

`generate_images()` использует `asyncio.gather(..., return_exceptions=True)` — если одна из N картинок упала, остальные публикуются. В UI юзер просто видит меньше картинок, чем ожидалось, без ошибок.

---

## Уведомления и настройки

### Per-user расписание

Каждый юзер сам выбирает **во сколько** и **в какие дни** хочет напоминания.

Хранится в БД:
- `users.notification_time` — `"HH:MM"` (локальное время сервера), дефолт `"18:00"`
- `users.notification_days_json` — JSON-список int (0=Mon, 6=Sun), дефолт `[0,1,2,3,4,5,6]`
- `users.daily_notifications` — bool, on/off глобально

### UI в боте — `/settings`

```
⚙️ Settings

Reminders: ✅ enabled
Time: 18:00
Days: weekdays (Mon–Fri)
Topics: AI Agents, LLMs

[🔕 Disable reminders]
[⏰ Change time]
[📅 Change days]
[🎯 Change topics]
[« Back]
```

**Picker времени** — две страницы:
```
⏰ Pick the hour              ⏰ Pick the minutes
                              Hour selected: 09:??
[00] [01] [02] [03]           [09:00] [09:15]
[04] [05] [06] [07]           [09:30] [09:45]
[08] [09] [10] [11]           [« Choose another hour]
...
[20] [21] [22] [23]
[« Back to settings]
```

**Picker дней** — чекбоксы с пресетами:
```
📅 Pick the days
Currently: every day

[✅ Mon] [✅ Tue] [✅ Wed] [✅ Thu]
[✅ Fri] [✅ Sat] [✅ Sun]
[📆 Every day] [💼 Weekdays] [🏖 Weekends]
[✔️ Save]
```

Чекбоксы тогглятся inline (без отправки нового сообщения). Пресеты — для быстрого выбора популярных вариантов.

### Шедулер

`backend/bot/scheduler.py::notification_tick()` — APScheduler cron, фаерится **каждую минуту в `:00` секунд**. Внутри:
1. Получает текущее `HH:MM` (server local time) и текущий weekday
2. Запрашивает из БД юзеров, у которых `notification_time == HH:MM` и `weekday IN notification_days`, авторизованных в LinkedIn и с балансом ≥ `COST_PER_POST_CENTS`
3. Шлёт каждому пуш через `send_daily_nudge()`

**Часовой пояс**: всё в local time сервера. Если нужен per-user TZ — TODO, добавляется отдельным полем в `users`.

---

## API эндпоинты

FastAPI слушает порт 8000.

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/health` | Healthcheck для docker / мониторинга. Всегда `{"status":"ok"}` |
| `GET` | `/api/admin/stats` | Метрики: users / generations / выручка |
| `GET` | `/oauth/callback` | LinkedIn редиректит сюда после согласия (PROD only) |
| `GET` | `/docs` | Swagger UI (автогенерируется FastAPI) |
| `GET` | `/openapi.json` | OpenAPI спека |

### `/api/admin/stats` — формат ответа

```json
{
  "users": {
    "total": 42,
    "authorized": 38
  },
  "generations": {
    "pending":   0,
    "generated": 2,
    "published": 156,
    "failed":    7
  },
  "money": {
    "topups_usd": 250.0,
    "spent_usd":  156.0
  }
}
```

> Эндпоинт открыт. Закрой его перед публикацией прода (см. [security-чеклист](#security-чеклист-для-prod)).

---

## Схема базы данных

Файл: `backend/db/models.py`. Схема управляется через **Alembic** — см. секцию [Миграции](#миграции-бд).

### `users`

| Поле | Тип | Описание |
|---|---|---|
| `id` | PK int | внутренний ID |
| `telegram_id` | bigint UNIQUE | Telegram user_id |
| `telegram_username` | string | @username |
| `telegram_first_name` | string | имя из TG |
| `linkedin_person_urn` | string | `urn:li:person:abc` |
| `linkedin_access_token` | text | OAuth-токен (per-user) |
| `linkedin_token_expires_at` | datetime | дата истечения токена |
| `oauth_state` | string | временный state для OAuth |
| `interests_json` | text | JSON: список slug'ов категорий |
| `daily_notifications` | bool | вкл/выкл напоминаний (глобально) |
| `notification_time` | string(5) | `"HH:MM"`, время напоминания (local server time) |
| `notification_days_json` | text | JSON: список int 0..6 (0=Mon, 6=Sun) |
| `balance_cents` | int | баланс в центах |
| `created_at` / `updated_at` | datetime | стандартные timestamps |

### `generations`

| Поле | Тип | Описание |
|---|---|---|
| `id` | PK int | |
| `user_id` | FK | → users.id |
| `topic` | text | тема, которую попросил юзер |
| `post_text` | text | сгенерированный текст |
| `image_prompts_json` | text | JSON: список промптов картинок |
| `image_paths_json` | text | JSON: список путей к сгенерированным PNG |
| `linkedin_post_id` | string | URN опубликованного поста |
| `cost_cents` | int | сколько списано |
| `status` | enum | pending / generated / published / failed |
| `error` | text | если упало — текст ошибки |
| `created_at` / `updated_at` | datetime | |

### `payments`

| Поле | Тип | Описание |
|---|---|---|
| `id` | PK int | |
| `user_id` | FK | → users.id |
| `amount_cents` | int | сколько начислено |
| `method` | string | 'mock' / 'stripe' / 'yookassa' / ... |
| `status` | enum | pending / completed / failed |
| `note` | string | произвольное описание |
| `created_at` | datetime | |

---

## Миграции БД

Схема управляется через [Alembic](https://alembic.sqlalchemy.org). Файлы:

```
alembic/
├── env.py                       # настройка (читает DATABASE_URL из настроек)
├── script.py.mako               # шаблон новой миграции
└── versions/
    └── 0001_initial.py          # текущие версии
alembic.ini                      # конфиг
```

### В docker-compose

Оба compose-файла включают сервис `migrations`, который запускает `alembic upgrade head` **до** старта `api`/`bot`:

```yaml
api:
  depends_on:
    migrations:
      condition: service_completed_successfully
```

Так что `docker compose up` → миграции накатываются автоматически.

### Вручную (без docker)

```bash
alembic upgrade head           # накатить все миграции
alembic current                # посмотреть текущую версию
alembic history                # вся история
alembic downgrade -1           # откатить на одну назад
```

### Добавить новую миграцию

После изменения моделей в `backend/db/models.py`:

```bash
# 1. Сгенерировать миграцию автоматически по diff'у моделей и БД
alembic revision --autogenerate -m "add user timezone" --rev-id 0002

# 2. Проверить и поправить файл alembic/versions/0002_add_user_timezone.py

# 3. Применить
alembic upgrade head
```

> **Важно:** `--autogenerate` не ловит все изменения (rename колонок, custom CHECK constraints и т.п.). Всегда читай сгенерированный файл перед коммитом.

### Если уже есть БД от старой версии без alembic_version

```bash
# Помечаем существующую БД как соответствующую миграции 0001 (не выполняя её)
alembic stamp 0001
# Дальше любые новые миграции накатятся нормально
alembic upgrade head
```

### Сброс БД с нуля

```bash
# DEV (SQLite)
rm backend/data/app.db
docker compose -f docker-compose.dev.yml up   # migrations создадут схему

# PROD (Postgres)
docker compose -f docker-compose.prod.yml down -v   # -v удаляет volume
docker compose -f docker-compose.prod.yml up -d
```

---

## Структура проекта и модули

```
LinkedIn/
├── Dockerfile                  # один образ для обоих сервисов
├── .dockerignore
├── docker-compose.dev.yml      # DEV: SQLite + mock LinkedIn + hot-reload
├── docker-compose.prod.yml     # PROD: Postgres + реальный LinkedIn
├── .env / .env.example
│
└── backend/
    ├── app.py                  # FastAPI: /oauth/callback, /api/admin/stats, /api/health
    ├── config.py               # pydantic-settings — все настройки из .env
    ├── logger.py               # настройка логирования (формат + уровни)
    ├── proxy.py                # SOCKS5 — get_proxies() + configure_env_proxy()
    ├── paths.py                # REPO_ROOT, BACKEND_DIR
    ├── requirements.txt
    │
    ├── generator.py            # Gemini text gen + Google Search grounding
    ├── images.py               # OpenAI gpt-image-1 → PNG в generated_images/ (multi-image)
    ├── linkedin.py             # LinkedInClient: upload_image + publish
    │
    ├── bot/                    # ── Telegram bot ───────────────────────
    │   ├── main.py             #    точка входа: создаёт Bot+Dispatcher, стартует scheduler
    │   ├── handlers.py         #    все @router.message / @router.callback_query
    │   ├── keyboards.py        #    inline-клавиатуры (main_menu, interests, topup, ...)
    │   ├── messages.py         #    все шаблоны сообщений (HTML)
    │   ├── scheduler.py        #    APScheduler cron 18:00 → daily_job
    │   ├── notifier.py         #    шлёт сообщения извне бота (из FastAPI callback)
    │   └── deps.py             #    singleton-доступ к Bot для notifier
    │
    ├── db/                     # ── SQLAlchemy async ──────────────────
    │   ├── models.py           #    User, Generation, Payment + enums
    │   ├── session.py          #    AsyncEngine, session_scope() context manager
    │   └── crud.py             #    атомарные CRUD-функции
    │
    ├── services/               # ── Бизнес-логика ────────────────────
    │   ├── oauth_service.py    #    start_oauth, complete_oauth, mock_authorize
    │   ├── billing_service.py  #    topup_mock, charge_for_generation, get_balance
    │   ├── posting_service.py  #    run_pipeline — оркестрация генерации+публикации+биллинга
    │   └── interests.py        #    каталог интересов + label()
    │
    ├── data/                   # SQLite база (DEV only) — в .gitignore
    └── generated_images/       # PNG из Gemini — в .gitignore
```

### Где что искать

| Хочешь поменять | Файл |
|---|---|
| Текст любого сообщения бота | `backend/bot/messages.py` |
| Новая команда `/foo` | `backend/bot/handlers.py` → `@router.message(Command("foo"))` |
| Поменять цену | `.env` → `COST_PER_POST_CENTS` |
| Добавить новую категорию интересов | `backend/services/interests.py` → INTERESTS dict |
| Сменить время напоминания | `.env` → `DAILY_NOTIFICATION_TIME` |
| Сменить text-LLM | `backend/generator.py` → `model="gemini-3.1-flash-lite"` |
| Сменить image-модель | `backend/images.py` → `IMAGE_MODEL` |
| Подкрутить инструкции к посту/инфографике | `backend/generator.py` → `SYSTEM_PROMPT_TEMPLATE` |
| Качество картинок (цена/qual) | `.env` → `IMAGE_QUALITY=low|medium|high` |
| Сколько картинок генерить | `.env` → `MAX_IMAGES_PER_POST=1..4` |

---

## Мониторинг и логи

### Логи docker

```bash
docker compose -f docker-compose.dev.yml logs -f               # все сервисы
docker compose -f docker-compose.dev.yml logs -f bot           # только бот
docker compose -f docker-compose.prod.yml logs -f --tail 100   # последние 100 строк
```

Формат логов (`backend/logger.py`):
```
22:39:06 [INFO    ] backend.bot.handlers — New user registered | tg_id=12345 username=ivan
22:40:01 [INFO    ] backend.services.posting_service — Pipeline start | user=12345 gen_id=42 topic='LLM inference'
22:40:45 [INFO    ] backend.services.posting_service — Pipeline done | user=12345 gen_id=42 post_id=urn:li:share:xxx balance=200
```

Шумные сторонние библиотеки (`httpx`, `urllib3`, `google`) приглушены до WARNING.

### Метрики через HTTP

```bash
curl http://localhost:8000/api/admin/stats | jq
```

### Прямой доступ к БД

```bash
# DEV (SQLite)
sqlite3 backend/data/app.db
sqlite> SELECT telegram_username, balance_cents, is_authorized FROM users;
sqlite> SELECT id, topic, status FROM generations ORDER BY id DESC LIMIT 10;

# PROD (Postgres)
docker compose -f docker-compose.prod.yml exec db psql -U bot -d linkedin_bot
linkedin_bot=# SELECT telegram_username, balance_cents FROM users;
```

### Healthcheck

Compose сам пингует `/api/health` каждые 30 секунд. Если 3 раза подряд не ответил — контейнер помечается unhealthy. `bot` стартует только после healthy `api`.

---

## Расширение

### Добавить новую команду

`backend/bot/handlers.py`:
```python
@router.message(Command("my_command"))
async def cmd_my_command(message: Message) -> None:
    await message.answer("Привет!")
```

### Добавить новую категорию интересов

`backend/services/interests.py`:
```python
INTERESTS: dict[str, str] = {
    ...
    "quantum": "⚛️ Quantum Computing",
}
```

Бот сразу её увидит при следующем запуске — миграции не нужны (хранится в `users.interests_json`).

### Поменять время daily nudge

`.env`:
```env
DAILY_NOTIFICATION_TIME=09:30
```

Время в UTC контейнера. Если хочешь Moscow time — добавь `TZ=Europe/Moscow` в `environment:` в docker-compose.

### Прикрутить реальный платёж

См. секцию [Биллинг](#биллинг).

### Добавить новый источник поиска (вместо Google Search)

В `backend/generator.py` сейчас используется `types.Tool(google_search=types.GoogleSearch())`. Можно заменить на собственный tool с веб-поиском через Tavily / SerpAPI / Brave Search — добавь tool в `GenerateContentConfig(tools=[...])` и обработай tool-calls в response.

---

## Troubleshooting

### Бот не отвечает на `/start`

1. Проверь логи: `docker compose -f docker-compose.dev.yml logs bot`
2. Должно быть: `Бот запускается...`. Если нет — проверь `TELEGRAM_BOT_TOKEN`.
3. Если есть `aiogram.exceptions.TelegramUnauthorizedError` — токен невалиден.

### "JSON parse error от Gemini"

Иногда Gemini возвращает текст до/после JSON. Парсер использует `raw_decode()` — должен справляться. Если падает — в логах будет полный ответ Gemini. Возможно стоит подкрутить системный промпт.

### "models/X is not found"

Gemini-модели регулярно меняют имена. Получи актуальный список:
```bash
docker compose -f docker-compose.dev.yml exec bot python -c "
from google import genai; import os
c = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
for m in c.models.list(): print(m.name)
"
```
И поправь в `backend/generator.py` (модель текста) или `backend/images.py` (`IMAGE_MODEL`).

### OAuth в PROD: "redirect_uri does not match"

URL в LinkedIn App и `PUBLIC_BASE_URL` в `.env` должны совпадать символ в символ, включая `http`/`https` и порт.

### "OAuth state не найден или истёк"

Юзер открыл OAuth-ссылку, потом удалил/перерегился в боте. State потерялся. Скажи юзеру нажать /start заново — сгенерится новый.

### Postgres не стартует

Проверь что `POSTGRES_PASSWORD` задан в `.env` и не пустой. Compose валидирует через `${POSTGRES_PASSWORD:?}`.

### "Не удалось уведомить пользователя в Telegram"

В PROD-режиме api и bot работают в **разных контейнерах**, у них **разные процессы**. Singleton `set_bot()` в одном процессе не виден другому. На практике это значит: пуш-уведомление об успешной OAuth-привязке не дойдёт. Юзер вернётся в бот вручную и увидит что привязан.

Решение для прода: либо запускать бот и api в одном процессе (объединить в одном `main.py` через `asyncio.gather()`), либо сделать pub/sub через Redis.

### Картинки не генерируются (OpenAI ошибка)

`gpt-image-1` требует включённого **Billing** на аккаунте OpenAI. Если получаешь 403/quota — зайди в [platform.openai.com → Billing](https://platform.openai.com/account/billing/overview) и добавь карту.

Если в логах `400 invalid_value: size`/`quality` — это значит SDK устарел. Проверь что `openai>=1.50.0` в `backend/requirements.txt`.

### Картинки шакального качества или без текста

Скорее всего стоит `IMAGE_QUALITY=low`. Подними до `medium` (по умолчанию) или `high`. Учти что `high` стоит ~$0.17 за картинку — при 2 картинках на пост это $0.34, что больше $1-долларовой цены за пост → подкрути `COST_PER_POST_CENTS` в `.env`.

### Gemini вернул слишком много / нерелевантных картинок

Подкрути `MAX_IMAGES_PER_POST` в `.env` (по умолчанию 2). Системный промпт уже инструктирует Gemini выбирать оптимальное количество в зависимости от поста.

---

## Security-чеклист для PROD

- [ ] `POSTGRES_PASSWORD` — сильный, сгенерён через `openssl rand -base64 32`
- [ ] `.env` не закоммичен в git (`git check-ignore .env` должно сработать)
- [ ] `/api/admin/stats` закрыт за nginx basic-auth, либо вынесен на 127.0.0.1
- [ ] HTTPS поднят (nginx/caddy/traefik впереди FastAPI)
- [ ] LinkedIn App в **Production** state (а не Dev) — иначе токены живут только 24 часа
- [ ] Порт Postgres (5432) **не проброшен наружу** — в `docker-compose.prod.yml` его нет, остаётся только внутри docker network ✅
- [ ] Логи не утекают наружу (Stripe/Telegram токены не печатаются — в текущей реализации они не логируются ✅)
- [ ] Backup БД: `docker exec linkedin-bot-db pg_dump -U bot linkedin_bot > backup.sql` (повесь на cron)

---

## Известные ограничения / TODO

- [ ] **Реальные платежи** — сейчас mock. Прикрути Stripe webhook (см. [Биллинг](#биллинг)).
- [ ] **Refresh-токены LinkedIn** — access_token живёт 60 дней, refresh не используется. Юзер сам перепривязывает через `/start` по истечении.
- [ ] **Auth на `/api/admin/stats`** — открытый эндпоинт, закрой через nginx / internal port перед публикацией.
- [ ] **OAuth callback нотификация в TG** работает только если bot и api в одном процессе (singleton bot instance). Для split-deploy нужен Redis pub/sub.
- [ ] **LinkedIn endpoints устарели** — `/v2/ugcPosts` + `/v2/assets` ещё работают, но supported path: `/rest/posts` + `/rest/images?action=initializeUpload`.
- [ ] **Rate limit на генерацию** — нет защиты от спама `/generate` (только балансовый лимит).
- [ ] **Per-user timezone** — сейчас все юзеры в server local time. Добавляется отдельным полем `users.timezone`.
- [ ] **HTTPS termination** — не входит в compose. Поставь nginx/caddy впереди.
- [ ] **Метрики Prometheus** — нет. Сейчас только `/api/admin/stats` с JSON.
- [ ] **Sentry / error tracking** — нет интеграции, только локальный логгер.
