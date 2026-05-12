"""
Singleton-доступ к экземпляру бота из других модулей (например, FastAPI колбэк).
"""

from __future__ import annotations

from typing import Optional

from aiogram import Bot

_bot: Optional[Bot] = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


def get_bot() -> Optional[Bot]:
    return _bot
