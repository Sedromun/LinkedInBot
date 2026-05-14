"""
config.py — централизованные настройки из .env через pydantic-settings.

Использование:
    from backend.config import settings
    settings.telegram_bot_token
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.paths import REPO_ROOT


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

    # Google AI (текст)
    google_api_key: str = ""

    # OpenAI (картинки — gpt-image-1)
    openai_api_key: str = ""
    image_quality: str = "medium"        # low | medium | high
    max_images_per_post: int = 2         # 1..4 — верхняя граница для Gemini

    # Прокси
    socks5_proxy: str = ""

    # Telegram
    telegram_bot_token: str = ""

    # LinkedIn режим
    mock_linkedin: bool = True

    # Публичный URL (для OAuth-колбэка) — нужен только когда mock_linkedin=False
    public_base_url: str = ""

    # Биллинг
    cost_per_post_cents: int = 100   # полная генерация + публикация
    regen_text_cents: int = 50       # перегенерация только текста
    initial_balance_cents: int = 300

    # БД
    database_url: str = f"sqlite+aiosqlite:///{REPO_ROOT}/backend/data/app.db"

    @property
    def oauth_redirect_uri(self) -> str:
        base = self.public_base_url.rstrip("/")
        return f"{base}/oauth/callback"


settings = Settings()
