"""
images.py — генерация инфографик с fallback-цепочкой по провайдерам.

Fallback-цепочка (картинки):
  1. gpt-image-2               (OpenAI, новый)
  2. gpt-image-1               (OpenAI, проверенный)
  3. nano-banana-pro-preview   (Google/Gemini, через generate_content + IMAGE modality)
  4. gemini-3.1-flash-image-preview (Google/Gemini, ещё один image-fallback)

Переключается только при 503 / UNAVAILABLE / недоступности модели.
Параллельная генерация N картинок через asyncio.gather.
"""

import asyncio
import base64
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from openai import OpenAI
from google import genai
from google.genai import types

from backend.config import settings
from backend.logger import get_logger
from backend.paths import BACKEND_DIR
from backend.proxy import configure_env_proxy

configure_env_proxy()

log = get_logger(__name__)

OUTPUT_DIR = BACKEND_DIR / "generated_images"

# Маппинг aspect_ratio → размер для OpenAI image API (только три поддерживаемых)
_OPENAI_SIZE_MAP = {
    "16:9": "1536x1024",
    "4:3":  "1536x1024",
    "1:1":  "1024x1024",
    "9:16": "1024x1536",
    "3:4":  "1024x1536",
}


# ── Цепочка image-моделей ────────────────────────────────────────────────────

class ImageProvider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


@dataclass
class ImageModelConfig:
    provider: ImageProvider
    model_id: str


IMAGE_MODEL_CHAIN: list[ImageModelConfig] = [
    ImageModelConfig(ImageProvider.OPENAI, "gpt-image-2"),
    ImageModelConfig(ImageProvider.OPENAI, "gpt-image-1"),
    ImageModelConfig(ImageProvider.GEMINI, "nano-banana-pro-preview"),
    ImageModelConfig(ImageProvider.GEMINI, "gemini-3.1-flash-image-preview"),
]


# ── Определение временной недоступности ──────────────────────────────────────

def _is_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "503", "unavailable", "overload", "high demand",
        "try again later", "temporarily", "capacity",
        "not found", "404",   # модель ещё не выкатили — переходим к следующей
    ))


# ── OpenAI image генератор ───────────────────────────────────────────────────

def _openai_generate(prompt: str, model_id: str, aspect_ratio: str) -> bytes:
    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не задан в .env")

    size = _OPENAI_SIZE_MAP.get(aspect_ratio, "1536x1024")
    quality = settings.image_quality

    client = OpenAI(api_key=api_key, timeout=180.0)
    response = client.images.generate(
        model=model_id,
        prompt=prompt,
        size=size,
        quality=quality,
        n=1,
    )
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError(f"OpenAI ({model_id}) не вернул b64_json")
    return base64.b64decode(response.data[0].b64_json)


# ── Gemini image генератор ───────────────────────────────────────────────────

def _gemini_generate(prompt: str, model_id: str, aspect_ratio: str) -> bytes:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY не задан в .env")

    client = genai.Client(api_key=api_key)

    # Gemini image models используют generate_content + response_modalities=["IMAGE"]
    # aspect_ratio передаём в промпт (ImageConfig поддерживается не всеми версиями SDK)
    _ASPECT_HINTS = {
        "16:9": "Wide cinematic 16:9 landscape aspect ratio.",
        "9:16": "Vertical 9:16 portrait aspect ratio.",
        "1:1":  "Square 1:1 aspect ratio.",
        "4:3":  "Standard 4:3 landscape aspect ratio.",
        "3:4":  "Vertical 3:4 portrait aspect ratio.",
    }
    aspect_hint = _ASPECT_HINTS.get(aspect_ratio, "")
    full_prompt = f"{prompt.rstrip('.')}. {aspect_hint}".strip() if aspect_hint else prompt

    config_kwargs: dict = {"response_modalities": ["IMAGE"]}
    try:
        config_kwargs["image_config"] = types.ImageConfig(aspect_ratio=aspect_ratio)
    except (AttributeError, TypeError):
        pass  # старый SDK без ImageConfig — полагаемся на текст промпта

    response = client.models.generate_content(
        model=model_id,
        contents=full_prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )

    try:
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                return part.inline_data.data
    except (IndexError, AttributeError):
        pass

    raise RuntimeError(f"Gemini ({model_id}) не вернул картинку в ответе")


_PROVIDER_FN = {
    ImageProvider.OPENAI: _openai_generate,
    ImageProvider.GEMINI: _gemini_generate,
}


# ── Генерация одной картинки с fallback ──────────────────────────────────────

def generate_image(prompt: str, aspect_ratio: str = "16:9") -> str:
    """
    Синхронно генерирует одну картинку, проходя по IMAGE_MODEL_CHAIN.
    Возвращает путь к PNG.
    Используется в asyncio.to_thread() из верхних слоёв.
    """
    last_exc: Exception | None = None

    for model in IMAGE_MODEL_CHAIN:
        log.info("Генерирую картинку | %s/%s | aspect=%s | prompt: %s…",
                 model.provider.value, model.model_id, aspect_ratio,
                 prompt[:80].replace("\n", " "))
        try:
            image_bytes = _PROVIDER_FN[model.provider](prompt, model.model_id, aspect_ratio)
            path = str(_save_image(image_bytes))
            log.info("Картинка готова: %s/%s → %s", model.provider.value, model.model_id, path)
            return path

        except Exception as exc:
            if _is_unavailable(exc):
                log.warning("Image модель %s/%s недоступна, пробую следующую: %s",
                            model.provider.value, model.model_id, exc)
                last_exc = exc
                continue
            log.exception("Ошибка image %s/%s (не связана с доступностью)",
                          model.provider.value, model.model_id)
            raise

    raise RuntimeError(
        f"Все image-модели недоступны. Последняя ошибка: {last_exc}"
    ) from last_exc


# ── Параллельная генерация N картинок ────────────────────────────────────────

async def generate_images(prompts: list[str], aspect_ratio: str = "16:9") -> list[str]:
    """
    Параллельно генерирует N картинок (каждая со своим fallback-chain).
    Упавшие — пропускаются gracefully.
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
            log.warning("Картинка #%d упала (все модели исчерпаны): %s", i + 1, res)
        else:
            paths.append(res)

    log.info("Готово: %d из %d картинок", len(paths), len(prompts))
    return paths


# ── Сохранение ───────────────────────────────────────────────────────────────

def _save_image(image_bytes: bytes) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"post_{int(time.time() * 1000)}_{os.getpid()}.png"
    filepath = OUTPUT_DIR / filename
    filepath.write_bytes(image_bytes)
    log.info("Сохранено: %s (%d KB)", filepath, filepath.stat().st_size // 1024)
    return filepath
