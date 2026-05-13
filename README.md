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
10. [API эндпоинты](#api-эндпоинты)
11. [Схема базы данных](#схема-базы-данных)
12. [Структура проекта и модули](#структура-проекта-и-модули)
13. [Мониторинг и логи](#мониторинг-и-логи)
14. [Расширение](#расширение)
15. [Troubleshooting](#troubleshooting)
16. [Security-чеклист для PROD](#security-чеклист-для-prod)
17. [Известные ограничения / TODO](#известные-ограничения--todo)

---

## Что под капотом

| Слой | Технология |
|---|---|
| Telegram bot | [aiogram v3](https://docs.aiogram.dev) (async) |
| Web / OAuth callback | [FastAPI](https://fastapi.tiangolo.com) + uvicorn |
| LLM (текст + дизайн промптов картинок) | Gemini 3.1 Flash Lite + встроенный Google Search |
| Картинки (инфографика) | **OpenAI `gpt-image-1`** — рисует чёткий текст внутри картинки |
| LinkedIn API | `/v2/ugcPosts` + `/v2/assets` (OAuth 2.0, multi-image) |
| Хранилище | SQLite (DEV) / Postgres 16 (PROD), SQLAlchemy 2.0 async |
| Шедулер | APScheduler (`AsyncIOScheduler`) |
| Контейнеризация | Docker + docker compose |
| Конфиг | pydantic-settings |

### Почему два разных LLM-провайдера

**Gemini** хорош в reasoning + у него есть встроенный Google Search → используем для написания поста и для дизайна промптов картинок.

**OpenAI gpt-image-1** — единственная на данный момент image-модель, которая корректно рисует **читаемый текст внутри картинки** (заголовки, цифры, лейблы карточек). Это критично потому что картинки в нашем боте — не декорация, а инфографики с реальной информацией.

Pipeline для одного поста:
```
тема → Gemini ── текст поста ──┐
              └─ image_prompts ─┴─ параллельно ─→ gpt-image-1 × N → инфографики
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
| `OPENAI_API_KEY` | ✅ | ✅ | [platform.openai.com](https://platform.openai.com/api-keys) — gpt-image-1 для картинок |
| `IMAGE_QUALITY` | `medium` | `medium` | `low` ($0.011) / `medium` ($0.04) / `high` ($0.17) на картинку |
| `MAX_IMAGES_PER_POST` | `2` | `2` | Сколько максимум картинок Gemini может попросить (1-4) |
| `TELEGRAM_BOT_TOKEN` | ✅ | ✅ | [@BotFather](https://t.me/BotFather) → /newbot |
| `LINKEDIN_CLIENT_ID` | — | ✅ | LinkedIn App → Auth |
| `LINKEDIN_CLIENT_SECRET` | — | ✅ | LinkedIn App → Auth |
| `PUBLIC_BASE_URL` | — | ✅ | Например `http://1.2.3.4:8000` |
| `POSTGRES_PASSWORD` | — | ✅ | `openssl rand -base64 32` |
| `COST_PER_POST_CENTS` | `100` | `100` | Цена за один пост (100 = $1) |
| `INITIAL_BALANCE_CENTS` | `300` | `300` | Бонус новому юзеру (300 = $3) |
| `DAILY_NOTIFICATION_TIME` | `18:00` | `18:00` | Время daily nudge (HH:MM, UTC контейнера) |
| `SOCKS5_PROXY` | — | — | Например `socks5://user:pass@host:1080` (опционально) |
| `DATABASE_URL` | автоматом | автоматом | Compose переопределяет — не трогай |

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

```
/start
  ├─ если новый: создать User, начислить $3, показать welcome
  └─ показать главное меню

[🔗 Привязать LinkedIn]  (кнопка появляется если не привязан)
  ├─ DEV-режим: oauth_service.mock_authorize() → fake-токен → "✓ привязан"
  └─ PROD-режим:
       1. start_oauth() — генерит state, сохраняет в БД
       2. бот шлёт https://www.linkedin.com/oauth/v2/authorization?…&state=…
       3. юзер кликает → логинится → жмёт Allow
       4. LinkedIn редиректит на /oauth/callback?code=…&state=…
       5. FastAPI находит юзера по state, обменивает code на access_token
       6. сохраняет токен + person_urn в БД
       7. notify_oauth_success() шлёт пуш в TG: "✅ LinkedIn привязан"

[🎯 Интересы]
  └─ показать чекбокс-клавиатуру → каждый клик токлит slug → "✔️ Готово"

[✨ Сгенерить пост] или /generate
  ├─ запросить тему / "🎲 Подобрать из интересов"
  ├─ posting_service.run_pipeline():
  │    1. проверить балaнс ≥ $1
  │    2. создать Generation(PENDING)
  │    3. generate_post_content() — Gemini + Google Search
  │    4. generate_images() — gpt-image-1 (параллельно N штук)
  │    5. (если PROD) LinkedInClient.publish() → post_id
  │    6. charge_for_generation() — списать $1
  │    7. update Generation → PUBLISHED
  └─ показать юзеру картинку + текст + ссылку на LinkedIn пост

Каждый день в 18:00 (по серверу):
  scheduler.daily_job()
    └─ для всех User where daily_notifications=true and authorized and balance≥$1:
        send_daily_nudge() — "🔔 Время для нового поста!"
```

---

## Биллинг

| Параметр | Дефолт | Где меняется |
|---|---|---|
| Цена за пост | $1.00 (100 центов) | `.env` → `COST_PER_POST_CENTS` |
| Стартовый баланс | $3.00 | `.env` → `INITIAL_BALANCE_CENTS` |
| Способ оплаты | Mock | `backend/services/billing_service.py::topup_mock` |
| Хранение | `users.balance_cents` (int) | Точность до цента |

### Правила списания

1. **Списание происходит ТОЛЬКО после успешной публикации.**
2. Если pipeline упал на любом этапе — деньги не уходят, в БД остаётся `Generation(status=FAILED, error=…)`.
3. Юзер с недостаточным балансом получит `InsufficientFunds` ещё до начала генерации (валидация на старте `run_pipeline`).

### Mock-пополнение

Кнопки `[$5] [$10] [$25]` в `/balance`. Деньги падают на баланс **моментально**, без реального платежа. В таблице `payments` создаётся запись `method='mock', status='completed'`.

### Прикручиваем реальный платёж (Stripe / ЮKassa)

1. Замени `topup_mock()` → создай pending Payment + сгенерь Stripe/ЮKassa URL
2. Добавь FastAPI webhook `/webhooks/stripe` → обнови Payment → credit_balance
3. В UI бота кнопка `[Пополнить]` теперь должна слать Stripe-ссылку, а не моментально начислять

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

Файл: `backend/db/models.py`. Создаётся автоматически при старте `api` через `Base.metadata.create_all()`.

### `users`

| Поле | Тип | Описание |
|---|---|---|
| `id` | PK int | внутренний ID |
| `telegram_id` | bigint UNIQUE | Telegram user_id |
| `telegram_username` | string | @username |
| `telegram_first_name` | string | имя из TG |
| `linkedin_person_urn` | string | `urn:li:person:abc` |
| `linkedin_access_token` | text | OAuth-токен |
| `linkedin_token_expires_at` | datetime | дата истечения токена |
| `oauth_state` | string | временный state для OAuth |
| `interests_json` | text | JSON-массив slugs |
| `daily_notifications` | bool | вкл/выкл daily nudge |
| `balance_cents` | int | баланс в центах |
| `created_at` / `updated_at` | datetime | стандартные timestamps |

### `generations`

| Поле | Тип | Описание |
|---|---|---|
| `id` | PK int | |
| `user_id` | FK | → users.id |
| `topic` | text | тема, которую попросил юзер |
| `post_text` | text | сгенерированный текст |
| `image_prompt` | text | промпт для картинки |
| `image_path` | string | путь к PNG |
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

- [ ] **Реальные платежи** — сейчас только mock. Прикрути Stripe webhook (см. [Биллинг](#биллинг)).
- [ ] **Refresh-токены LinkedIn** — access_token живёт 60 дней, refresh не используется. Через 60 дней юзер должен сам перепривязать через `/start`.
- [ ] **Миграции БД** — сейчас `Base.metadata.create_all()`. Для продакшен-эволюции схемы прикрути Alembic.
- [ ] **Auth на `/api/admin/stats`** — открытый эндпоинт.
- [ ] **OAuth callback нотификация в TG** работает только в одном процессе. Для split-deploy нужен Redis pub/sub или объединить bot+api в один процесс.
- [ ] **LinkedIn endpoints устарели** — `/v2/ugcPosts` + `/v2/assets` ещё работают, но supported path: `/rest/posts` + `/rest/images?action=initializeUpload`.
- [ ] **Rate limit на генерацию** — нет защиты от спама `/generate`. Юзер может попросить генерить пока баланс не кончится.
- [ ] **HTTPS termination** — не входит в compose. Поставь nginx/caddy впереди.
- [ ] **Метрики Prometheus** — нет. Сейчас только `/api/admin/stats` с JSON.
- [ ] **Sentry / error tracking** — нет интеграции, только локальный логгер.
