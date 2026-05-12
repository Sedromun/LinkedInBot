"""
Запуск Telegram бота:
  python -m backend.bot.main

Бот работает в long-polling режиме. Параллельно поднимается:
  - SQLite БД (создание таблиц при старте)
  - APScheduler с ежедневным напоминанием

FastAPI поднимать отдельной командой:
  uvicorn backend.app:app --host 0.0.0.0 --port 8000
"""

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from backend.bot import handlers
from backend.bot.deps import set_bot
from backend.bot.scheduler import start_scheduler, stop_scheduler
from backend.config import settings
from backend.db.session import init_db
from backend.logger import get_logger

log = get_logger(__name__)


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    await init_db()

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    set_bot(bot)  # делаем доступным для FastAPI колбэка

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)

    start_scheduler()

    log.info("Бот запускается...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        stop_scheduler()
        await bot.session.close()
        log.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Получен Ctrl+C, выхожу")
