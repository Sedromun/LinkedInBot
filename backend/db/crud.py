"""
CRUD-операции над моделями. Принимают AsyncSession.
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Generation,
    GenerationStatus,
    Payment,
    PaymentStatus,
    User,
)


# ── User ─────────────────────────────────────────────────────────────────────

async def get_user_by_tg(session: AsyncSession, tg_id: int) -> Optional[User]:
    res = await session.execute(select(User).where(User.telegram_id == tg_id))
    return res.scalar_one_or_none()


async def get_user_by_oauth_state(session: AsyncSession, state: str) -> Optional[User]:
    res = await session.execute(select(User).where(User.oauth_state == state))
    return res.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
    initial_balance_cents: int,
) -> User:
    user = User(
        telegram_id=tg_id,
        telegram_username=username,
        telegram_first_name=first_name,
        balance_cents=initial_balance_cents,
    )
    session.add(user)
    await session.flush()
    return user


async def get_or_create_user(
    session: AsyncSession,
    *,
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
    initial_balance_cents: int,
) -> tuple[User, bool]:
    """Возвращает (user, created)."""
    user = await get_user_by_tg(session, tg_id)
    if user:
        # обновляем username/first_name на случай если поменялись
        if user.telegram_username != username:
            user.telegram_username = username
        if user.telegram_first_name != first_name:
            user.telegram_first_name = first_name
        return user, False
    user = await create_user(
        session,
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        initial_balance_cents=initial_balance_cents,
    )
    return user, True


async def set_oauth_state(session: AsyncSession, user: User, state: Optional[str]) -> None:
    user.oauth_state = state


async def save_linkedin_tokens(
    session: AsyncSession,
    user: User,
    *,
    access_token: str,
    person_urn: str,
    expires_in_sec: int,
) -> None:
    user.linkedin_access_token = access_token
    user.linkedin_person_urn   = person_urn
    user.linkedin_token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in_sec)
    user.oauth_state = None


async def list_users_for_daily_notify(session: AsyncSession) -> Sequence[User]:
    """Авторизованные юзеры с включёнными уведомлениями (без фильтра по времени)."""
    stmt = (
        select(User)
        .where(User.daily_notifications.is_(True))
        .where(User.linkedin_access_token.is_not(None))
    )
    res = await session.execute(stmt)
    return res.scalars().all()


async def list_users_for_notify_at(
    session: AsyncSession,
    *,
    time_str: str,
    weekday: int,
) -> list[User]:
    """
    Возвращает авторизованных юзеров, которым нужно отправить уведомление
    в указанное время и день недели.

    Args:
        time_str: "HH:MM" формат, локальное время сервера
        weekday:  0=Monday, 6=Sunday (как datetime.weekday())
    """
    stmt = (
        select(User)
        .where(User.daily_notifications.is_(True))
        .where(User.linkedin_access_token.is_not(None))
        .where(User.notification_time == time_str)
    )
    res = await session.execute(stmt)
    users = res.scalars().all()

    # weekday фильтр в Python (хранится как JSON list)
    return [u for u in users if weekday in u.notification_days]


# ── Balance / Payments ───────────────────────────────────────────────────────

async def credit_balance(
    session: AsyncSession,
    user: User,
    amount_cents: int,
    *,
    method: str = "mock",
    note: Optional[str] = None,
) -> Payment:
    """Пополнить баланс + записать платёж."""
    user.balance_cents += amount_cents
    payment = Payment(
        user_id=user.id,
        amount_cents=amount_cents,
        method=method,
        status=PaymentStatus.COMPLETED,
        note=note,
    )
    session.add(payment)
    await session.flush()
    return payment


async def debit_balance(session: AsyncSession, user: User, amount_cents: int) -> bool:
    """Списать деньги. Возвращает False если не хватило."""
    if user.balance_cents < amount_cents:
        return False
    user.balance_cents -= amount_cents
    return True


# ── Generations ──────────────────────────────────────────────────────────────

async def create_generation(
    session: AsyncSession,
    user: User,
    topic: str,
) -> Generation:
    g = Generation(user_id=user.id, topic=topic, status=GenerationStatus.PENDING)
    session.add(g)
    await session.flush()
    return g


async def update_generation(
    session: AsyncSession,
    generation: Generation,
    **fields,
) -> None:
    for key, value in fields.items():
        setattr(generation, key, value)
