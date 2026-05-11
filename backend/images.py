"""
images.py — генерация изображений через Gemini 3.1 Flash Image Preview.

Gemini image-модели используют generate_content() с response_modalities=["IMAGE"],
а НЕ generate_images() — тот метод только для Imagen-моделей.
"""

import os
import time
from pathlib import Path

from google import genai
from google.genai import types

from backend.logger import get_logger
from backend.paths import BACKEND_DIR
from backend.proxy import configure_env_proxy

configure_env_proxy()  # применяем до создания genai.Client

log = get_logger(__name__)

OUTPUT_DIR = BACKEND_DIR / "generated_images"

IMAGE_MODEL = "gemini-3.1-flash-image-preview"


def generate_image(prompt: str, aspect_ratio: str = "16:9") -> str:
    """
    Генерирует изображение через Gemini image-модель и сохраняет локально.

    Args:
        prompt:       Текстовое описание картинки (английский)
        aspect_ratio: "16:9" | "1:1" | "9:16" | "4:3" | "3:4"

    Returns:
        Путь к сохранённому PNG файлу
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Не задан GOOGLE_API_KEY в .env")

    client = genai.Client(api_key=api_key)

    enhanced_prompt = _enhance_prompt(prompt)
    log.info("Генерирую картинку | model=%s | aspect_ratio=%s | prompt: %s…",
             IMAGE_MODEL, aspect_ratio, enhanced_prompt[:80])

    try:
        response = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=enhanced_prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
    except Exception:
        log.exception("Ошибка при обращении к Gemini image API (model=%s)", IMAGE_MODEL)
        raise

    # Извлекаем байты картинки из ответа
    image_bytes = _extract_image_bytes(response)

    log.info("Изображение сгенерировано (%d KB)", len(image_bytes) // 1024)

    local_path = _save_image(image_bytes)
    return str(local_path)


def _extract_image_bytes(response) -> bytes:
    """Достаёт inline_data из первого image-парта в ответе Gemini."""
    try:
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                return part.inline_data.data
    except (IndexError, AttributeError) as exc:
        log.error("Неожиданная структура ответа Gemini image: %s", exc)

    # Если ничего не нашли — логируем весь ответ для диагностики
    log.error("Не удалось извлечь картинку из ответа. Ответ: %s", response)
    raise RuntimeError(
        "Gemini не вернул картинку в ответе. "
        f"Candidates: {len(response.candidates) if response.candidates else 0}"
    )


def _enhance_prompt(prompt: str) -> str:
    """Добавляет технические детали стиля для лучшего результата."""
    style_suffix = (
        " Ultra-detailed, professional quality, suitable for LinkedIn. "
        "No text, no letters, no watermarks. "
        "Cinematic lighting, sharp focus, 4K quality."
    )
    if "no text" in prompt.lower() or "no letters" in prompt.lower():
        return prompt
    return prompt.rstrip(".") + "." + style_suffix


def _save_image(image_bytes: bytes) -> Path:
    """Сохраняет бинарные данные изображения в OUTPUT_DIR."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    filename = f"post_{int(time.time())}.png"
    filepath = OUTPUT_DIR / filename

    with open(filepath, "wb") as f:
        f.write(image_bytes)

    log.info("Картинка сохранена: %s (%d KB)", filepath, filepath.stat().st_size // 1024)
    return filepath
