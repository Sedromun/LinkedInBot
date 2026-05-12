"""
config.py — централизованные настройки из .env через pydantic-settings.

Использование:
    from backend.config import settings
    settings.telegram_bot_token
"""

from datetime import time
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.paths import REPO_ROOT


def _parse_time(s: str) -> time:
    hh, mm = s.split(":")
    return time(hour=int(hh), minute=int(mm))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LinkedIn
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_access_token: str = ""    # single-user fallback
    linkedin_person_urn: str = ""

    # Google AI
    google_api_key: str = ""

    # Прокси
    socks5_proxy: str = ""

    # Telegram
    telegram_bot_token: str = ""

    # LinkedIn режим
    mock_linkedin: bool = True

    # Публичный URL (для OAuth-колбэка) — нужен только когда mock_linkedin=False
    public_base_url: str = ""

    # Биллинг
    cost_per_post_cents: int = 100
    initial_balance_cents: int = 300
    daily_notification_time: str = "18:00"

    # БД
    database_url: str = f"sqlite+aiosqlite:///{REPO_ROOT}/backend/data/app.db"

    @property
    def oauth_redirect_uri(self) -> str:
        base = self.public_base_url.rstrip("/")
        return f"{base}/oauth/callback"

    @property
    def daily_time(self) -> time:
        return _parse_time(self.daily_notification_time)


settings = Settings()
