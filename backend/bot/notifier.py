"""
Вспомогательные функции для отправки сообщений пользователям ИЗВНЕ бота
(из FastAPI колбэка, из шедулера).
"""

from backend.bot import messages
from backend.bot.deps import get_bot
from backend.logger import get_logger

log = get_logger(__name__)


async def notify_oauth_success(tg_id: int) -> None:
    bot = get_bot()
    if bot is None:
        log.warning("Bot instance не задан — не могу уведомить tg=%s", tg_id)
        return
    try:
        await bot.send_message(tg_id, messages.OAUTH_SUCCESS, parse_mode="HTML")
    except Exception:
        log.exception("Не удалось послать OAuth success в TG (tg=%s)", tg_id)


async def send_daily_nudge(tg_id: int, topics: str, balance_cents: int, posts: int) -> None:
    bot = get_bot()
    if bot is None:
        return
    try:
        await bot.send_message(
            tg_id,
            messages.DAILY_NUDGE.format(
                topics=topics,
                balance=balance_cents / 100,
                posts=posts,
            ),
            parse_mode="HTML",
        )
    except Exception:
        log.exception("Не удалось послать daily nudge в TG (tg=%s)", tg_id)
