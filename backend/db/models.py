"""
SQLAlchemy модели для многопользовательского режима.

Таблицы:
    users        — пользователи Telegram + их LinkedIn-токены + баланс
    generations  — лог генераций (для аналитики, биллинга, мониторинга)
    payments     — лог пополнений (пока mock)
"""

from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class GenerationStatus(str, enum.Enum):
    PENDING    = "pending"     # начали генерить
    GENERATED  = "generated"   # текст + картинка готовы
    PUBLISHED  = "published"   # опубликовано в LinkedIn
    FAILED     = "failed"      # упало где-то


class PaymentStatus(str, enum.Enum):
    PENDING    = "pending"
    COMPLETED  = "completed"
    FAILED     = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Telegram
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    telegram_first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # LinkedIn OAuth
    linkedin_person_urn: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    linkedin_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Промежуточное состояние OAuth (один за раз)
    oauth_state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Профиль
    interests_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    daily_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Время напоминания "HH:MM" в локальном времени сервера
    notification_time: Mapped[str] = mapped_column(String(5), default="18:00", nullable=False)
    # JSON list[int] — дни недели: 0=Mon, 6=Sun. По умолчанию каждый день.
    notification_days_json: Mapped[str] = mapped_column(
        Text, default="[0,1,2,3,4,5,6]", nullable=False
    )

    # Баланс в центах ($1.00 = 100)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Метаданные
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    generations: Mapped[list["Generation"]] = relationship(back_populates="user", lazy="selectin")
    payments:    Mapped[list["Payment"]]    = relationship(back_populates="user", lazy="selectin")

    # ── Удобные геттеры/сеттеры для interests ────────────────────────────────

    @property
    def interests(self) -> list[str]:
        try:
            return json.loads(self.interests_json or "[]")
        except json.JSONDecodeError:
            return []

    @interests.setter
    def interests(self, value: list[str]) -> None:
        self.interests_json = json.dumps(value)

    # ── Notification days ──────────────────────────────────────────────────

    @property
    def notification_days(self) -> list[int]:
        """Список дней недели для уведомлений (0=Mon, 6=Sun)."""
        try:
            data = json.loads(self.notification_days_json or "[]")
            return [d for d in data if isinstance(d, int) and 0 <= d <= 6]
        except json.JSONDecodeError:
            return []

    @notification_days.setter
    def notification_days(self, value: list[int]) -> None:
        cleaned = sorted({int(d) for d in value if 0 <= int(d) <= 6})
        self.notification_days_json = json.dumps(cleaned)

    # ── Проверка авторизации ────────────────────────────────────────────────

    @property
    def is_authorized(self) -> bool:
        return bool(self.linkedin_access_token and self.linkedin_person_urn)

    @property
    def balance_usd(self) -> float:
        return self.balance_cents / 100


class Generation(Base):
    __tablename__ = "generations"

    id:      Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    topic:             Mapped[str]            = mapped_column(Text, nullable=False)
    post_text:         Mapped[Optional[str]]  = mapped_column(Text, nullable=True)

    # JSON: list[str] — промпты для каждой картинки
    image_prompts_json: Mapped[str]           = mapped_column(Text, default="[]", nullable=False)
    # JSON: list[str] — пути к сгенерированным PNG
    image_paths_json:   Mapped[str]           = mapped_column(Text, default="[]", nullable=False)

    linkedin_post_id:  Mapped[Optional[str]]  = mapped_column(String(128), nullable=True)

    cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus), default=GenerationStatus.PENDING, nullable=False
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="generations")

    # ── Удобные геттеры/сеттеры для JSON-полей ──────────────────────────────

    @property
    def image_prompts(self) -> list[str]:
        try:
            return json.loads(self.image_prompts_json or "[]")
        except json.JSONDecodeError:
            return []

    @image_prompts.setter
    def image_prompts(self, value: list[str]) -> None:
        self.image_prompts_json = json.dumps(value)

    @property
    def image_paths(self) -> list[str]:
        try:
            return json.loads(self.image_paths_json or "[]")
        except json.JSONDecodeError:
            return []

    @image_paths.setter
    def image_paths(self, value: list[str]) -> None:
        self.image_paths_json = json.dumps(value)


class Payment(Base):
    __tablename__ = "payments"

    id:      Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    method:       Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.COMPLETED, nullable=False
    )
    note:    Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="payments")
