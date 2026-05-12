"""
Шедулер ежедневных напоминаний.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.bot.notifier import send_daily_nudge
from backend.config import settings
from backend.db import crud
from backend.db.session import session_scope
from backend.logger import get_logger
from backend.services.interests import label

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def daily_job() -> None:
    """Шлёт всем авторизованным юзерам с включёнными уведомлениями nudge-сообщение."""
    log.info("Daily job started")
    sent = 0
    skipped = 0

    async with session_scope() as session:
        users = await crud.list_users_for_daily_notify(session)

    cost_cents = settings.cost_per_post_cents

    for user in users:
        if user.balance_cents < cost_cents:
            skipped += 1
            continue
        topics_str = ", ".join(label(s) for s in user.interests[:3]) or "(нет интересов)"
        posts = user.balance_cents // cost_cents if cost_cents else 0
        try:
            await send_daily_nudge(user.telegram_id, topics_str, user.balance_cents, posts)
            sent += 1
        except Exception:
            log.exception("Daily nudge failed for tg=%s", user.telegram_id)

    log.info("Daily job done | sent=%d skipped=%d total=%d", sent, skipped, len(users))


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = AsyncIOScheduler()
    t = settings.daily_time
    trigger = CronTrigger(hour=t.hour, minute=t.minute)
    sched.add_job(daily_job, trigger, id="daily_nudge", replace_existing=True)
    sched.start()
    _scheduler = sched
    log.info("Scheduler started | daily nudge at %s", settings.daily_notification_time)
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
