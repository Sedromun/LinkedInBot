"""
Асинхронный движок SQLAlchemy + фабрика сессий.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings
from backend.logger import get_logger

log = get_logger(__name__)


# Создаём директорию для SQLite-файла, если её ещё нет
if settings.database_url.startswith("sqlite"):
    # формат "sqlite+aiosqlite:///path/to/file.db"
    db_path = settings.database_url.split("///", 1)[-1]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


engine = create_async_engine(settings.database_url, future=True, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope():
    """
    Контекстный менеджер для async-сессии с автокоммитом/роллбэком.
    Использование:
        async with session_scope() as session:
            ...
    """
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# NB: схема БД управляется через Alembic. Запуск миграций:
#     alembic upgrade head
# В docker-compose это делается до старта api/bot (см. compose-файлы).
