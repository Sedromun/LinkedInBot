"""
Шедулер уведомлений с per-user расписанием.

Каждый юзер выбирает:
  - notification_time: "HH:MM" (локальное время сервера)
  - notification_days: список дней недели (0=Mon, 6=Sun)

Раз в минуту (в начале каждой минуты) шедулер проверяет: кому из юзеров
сейчас пора отправить напоминание, и шлёт им сообщения.
"""

from datetime import datetime

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


async def notification_tick() -> None:
    """
    Запускается каждую минуту в :00 секунд.
    Находит юзеров с notification_time == current_time и нужным weekday,
    и шлёт им nudge.
    """
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    current_weekday = now.weekday()  # 0=Mon, 6=Sun

    async with session_scope() as session:
        users = await crud.list_users_for_notify_at(
            session,
            time_str=current_time_str,
            weekday=current_weekday,
        )

    if not users:
        return

    log.info("Notification tick | time=%s weekday=%d → %d users",
             current_time_str, current_weekday, len(users))

    cost_cents = settings.cost_per_post_cents
    sent = 0
    skipped_no_funds = 0

    for user in users:
        if user.balance_cents < cost_cents:
            skipped_no_funds += 1
            continue

        topics_str = ", ".join(label(s) for s in user.interests[:3]) or "(no topics set)"
        posts = user.balance_cents // cost_cents if cost_cents else 0
        try:
            await send_daily_nudge(user.telegram_id, topics_str, user.balance_cents, posts)
            sent += 1
        except Exception:
            log.exception("Nudge failed for tg=%s", user.telegram_id)

    log.info("Notifications | sent=%d skipped_no_funds=%d", sent, skipped_no_funds)


def start_scheduler() -> AsyncIOScheduler:
    """Запускает per-minute проверку уведомлений."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = AsyncIOScheduler()
    # Раз в минуту, в :00 секунд (CronTrigger с указанной секундой)
    sched.add_job(
        notification_tick,
        CronTrigger(second=0),
        id="notification_tick",
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    log.info("Scheduler started | проверка уведомлений каждую минуту (per-user time)")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
