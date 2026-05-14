"""
Alembic env.py — миграции БД с async SQLAlchemy.

URL подключения берётся из backend.config.settings.database_url
(который читается из .env / переменных окружения).

Поддерживает оба бэкенда:
  - sqlite+aiosqlite (DEV)
  - postgresql+asyncpg (PROD)
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Гарантируем, что корень репозитория есть в sys.path — чтобы импортнуть backend.*
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings  # noqa: E402
from backend.db.models import Base   # noqa: E402

# ── Alembic config object ────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Подставляем URL из настроек (можно переопределить через env переменную)
db_url = os.getenv("DATABASE_URL") or settings.database_url
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


# ── Offline-режим (генерация SQL без подключения к БД) ──────────────────────

def run_migrations_offline() -> None:
    """Запуск миграций в offline-режиме (только генерация SQL)."""
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online-режим (реальное применение к БД) ─────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,           # ловить изменения типов колонок
        compare_server_default=True, # ловить изменения server_default
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Создаёт async-engine и запускает миграции через .run_sync()."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ──────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
