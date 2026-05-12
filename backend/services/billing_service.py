"""
Биллинг: пополнения (mock) и списания за генерацию.
"""

from backend.db import crud
from backend.db.models import User
from backend.db.session import session_scope
from backend.logger import get_logger

log = get_logger(__name__)


class InsufficientFunds(Exception):
    """Не хватило денег для списания."""


async def topup_mock(tg_id: int, amount_cents: int) -> int:
    """Пополнить баланс (mock — без реального платежа). Возвращает новый баланс."""
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            raise RuntimeError(f"User tg={tg_id} не найден")
        await crud.credit_balance(session, user, amount_cents, method="mock", note="manual topup")
        log.info("Balance topup | user=%s +%d cents → %d cents",
                 tg_id, amount_cents, user.balance_cents)
        return user.balance_cents


async def charge_for_generation(tg_id: int, cost_cents: int) -> int:
    """
    Списать цену за генерацию. Возвращает новый баланс.
    Бросает InsufficientFunds если недостаточно средств.
    """
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            raise RuntimeError(f"User tg={tg_id} не найден")
        ok = await crud.debit_balance(session, user, cost_cents)
        if not ok:
            log.warning("Insufficient funds | user=%s balance=%d need=%d",
                        tg_id, user.balance_cents, cost_cents)
            raise InsufficientFunds(
                f"Нужно ${cost_cents/100:.2f}, на балансе ${user.balance_cents/100:.2f}"
            )
        log.info("Balance debit | user=%s -%d cents → %d cents",
                 tg_id, cost_cents, user.balance_cents)
        return user.balance_cents


async def get_balance(tg_id: int) -> int:
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        return user.balance_cents if user else 0
