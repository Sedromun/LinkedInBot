"""
images.py — генерация инфографик-картинок через OpenAI gpt-image-1.

Почему gpt-image-1:
  - Корректно рисует ТЕКСТ внутри картинки (Gemini/DALL-E косячат с буквами)
  - Это критично для инфографик-стиля: заголовки, лейблы, цифры, код

Поддерживает параллельную генерацию N картинок (asyncio.gather).
"""

import asyncio
import base64
import os
import time
from pathlib import Path

from openai import OpenAI

from backend.config import settings
from backend.logger import get_logger
from backend.paths import BACKEND_DIR
from backend.proxy import configure_env_proxy

configure_env_proxy()

log = get_logger(__name__)

OUTPUT_DIR = BACKEND_DIR / "generated_images"

IMAGE_MODEL = "gpt-image-1"

# Маппинг aspect_ratio (то что приходит из API) → размер для gpt-image-1.
# gpt-image-1 поддерживает только три размера, поэтому маппим к ближайшему.
_SIZE_MAP = {
    "16:9": "1536x1024",   # landscape (3:2 на самом деле — ближайшее)
    "4:3":  "1536x1024",
    "1:1":  "1024x1024",
    "9:16": "1024x1536",   # portrait
    "3:4":  "1024x1536",
}


# ── Главные публичные функции ────────────────────────────────────────────────

def generate_image(prompt: str, aspect_ratio: str = "16:9") -> str:
    """
    Синхронно генерирует одну картинку и возвращает путь к PNG.
    Используется в asyncio.to_thread() из верхних слоёв.
    """
    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Не задан OPENAI_API_KEY в .env")

    size = _SIZE_MAP.get(aspect_ratio, "1536x1024")
    quality = settings.image_quality

    log.info(
        "Генерирую картинку | model=%s | size=%s | quality=%s | prompt: %s…",
        IMAGE_MODEL, size, quality, prompt[:100].replace("\n", " "),
    )

    client = OpenAI(api_key=api_key, timeout=180.0)
    try:
        response = client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )
    except Exception:
        log.exception("Ошибка при обращении к OpenAI image API (model=%s)", IMAGE_MODEL)
        raise

    if not response.data or not response.data[0].b64_json:
        log.error("OpenAI не вернул b64_json. Ответ: %s", response)
        raise RuntimeError("OpenAI не вернул изображение в ответе")

    image_bytes = base64.b64decode(response.data[0].b64_json)
    return str(_save_image(image_bytes))


async def generate_images(prompts: list[str], aspect_ratio: str = "16:9") -> list[str]:
    """
    Асинхронно генерирует N картинок ПАРАЛЛЕЛЬНО.
    Если одна из них упала — остальные продолжают; в результат попадают только успешные.

    Returns:
        list путей к PNG (порядок соответствует prompts, но битые — пропускаются)
    """
    if not prompts:
        return []

    log.info("Запускаю параллельную генерацию %d картинок (aspect_ratio=%s)",
             len(prompts), aspect_ratio)

    coroutines = [asyncio.to_thread(generate_image, p, aspect_ratio) for p in prompts]
    results = await asyncio.gather(*coroutines, return_exceptions=True)

    paths: list[str] = []
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            log.warning("Картинка #%d упала: %s", i + 1, res)
        else:
            paths.append(res)

    log.info("Готово: %d из %d картинок сгенерированы", len(paths), len(prompts))
    return paths


# ── Сохранение ───────────────────────────────────────────────────────────────

def _save_image(image_bytes: bytes) -> Path:
    """Пишет PNG в OUTPUT_DIR. Имя — timestamp + случайный суффикс (на случай гонки)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"post_{int(time.time() * 1000)}_{os.getpid()}.png"
    filepath = OUTPUT_DIR / filename
    filepath.write_bytes(image_bytes)
    log.info("Картинка сохранена: %s (%d KB)", filepath, filepath.stat().st_size // 1024)
    return filepath
