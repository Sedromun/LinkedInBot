"""Проверка переменных окружения для LinkedIn-постера."""

import os
from typing import TypedDict


class EnvKeyInfo(TypedDict):
    key: str
    description: str


LLM_ENV: list[EnvKeyInfo] = [
    {"key": "GOOGLE_API_KEY", "description": "Google AI API ключ (Gemini + Imagen)"},
]

IMAGE_ENV: list[EnvKeyInfo] = [
    {"key": "GOOGLE_API_KEY", "description": "Google AI API ключ (Imagen 3)"},
]

LINKEDIN_ENV: list[EnvKeyInfo] = [
    {"key": "LINKEDIN_ACCESS_TOKEN", "description": "Токен LinkedIn (python -m backend.auth)"},
    {"key": "LINKEDIN_PERSON_URN", "description": "Person URN LinkedIn"},
]

# Дедуплицируем: GOOGLE_API_KEY фигурирует в обоих, берём уникальные
REQUIRED_ALL: list[EnvKeyInfo] = LLM_ENV + LINKEDIN_ENV


def _missing_from(keys: list[EnvKeyInfo]) -> list[EnvKeyInfo]:
    seen: set[str] = set()
    missing: list[EnvKeyInfo] = []
    for item in keys:
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        val = os.getenv(item["key"], "")
        if not val or val.startswith("your_"):
            missing.append(item)
    return missing


def missing_env_keys() -> list[EnvKeyInfo]:
    """Все обязательные ключи (для статуса /api/env)."""
    return _missing_from(REQUIRED_ALL)


def missing_for_llm() -> list[EnvKeyInfo]:
    return _missing_from(LLM_ENV)


def missing_for_image() -> list[EnvKeyInfo]:
    return _missing_from(IMAGE_ENV)


def missing_for_linkedin() -> list[EnvKeyInfo]:
    return _missing_from(LINKEDIN_ENV)


def _raise_missing(missing: list[EnvKeyInfo], intro: str) -> None:
    if not missing:
        return
    lines = [f"  • {m['key']} — {m['description']}" for m in missing]
    raise RuntimeError(intro + "\n" + "\n".join(lines))


def require_llm_env() -> None:
    _raise_missing(
        missing_for_llm(),
        "Не хватает ключей для генерации текста (.env в корне репозитория):",
    )


def require_image_env() -> None:
    _raise_missing(
        missing_for_image(),
        "Не хватает ключей для Imagen 3:",
    )


def require_linkedin_env() -> None:
    _raise_missing(
        missing_for_linkedin(),
        "Не хватает ключей для LinkedIn:",
    )


def require_full_pipeline_env() -> None:
    """Gemini + Imagen + LinkedIn."""
    miss = _missing_from(REQUIRED_ALL)
    if miss:
        _raise_missing(miss, "Не заполнены переменные в .env:")
