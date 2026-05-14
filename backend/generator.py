"""
generator.py — генерация LinkedIn-поста с fallback-цепочкой провайдеров.

Fallback-цепочка (текст):
  1. gemini-3.1-flash-lite      (Google, дешёвый, со встроенным Google Search)
  2. gemini-3.1-pro-preview     (Google, мощнее)
  3. gemini-3-pro-preview       (Google, ещё один fallback)
  4. gpt-4.5-mini               (OpenAI, без web search)
  5. gpt-5.4                    (OpenAI)
  6. gpt-5.5                    (OpenAI)

Переключение: только на 503 / UNAVAILABLE / высокая нагрузка.
"""

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from google import genai
from google.genai import types
from openai import OpenAI

from backend.config import settings
from backend.logger import get_logger
from backend.proxy import configure_env_proxy

configure_env_proxy()

log = get_logger(__name__)


# ── Цепочка моделей ───────────────────────────────────────────────────────────

class Provider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"


@dataclass
class ModelConfig:
    provider:     Provider
    model_id:     str
    has_search:   bool = False    # умеет ли делать web-search сам


TEXT_MODEL_CHAIN: list[ModelConfig] = [
    ModelConfig(Provider.GEMINI, "gemini-3.1-flash-lite",  has_search=True),
    ModelConfig(Provider.GEMINI, "gemini-3.1-pro-preview", has_search=True),
    ModelConfig(Provider.GEMINI, "gemini-3-pro-preview",   has_search=True),
    ModelConfig(Provider.OPENAI, "gpt-4.5-mini",           has_search=True),
    ModelConfig(Provider.OPENAI, "gpt-5.4",                has_search=True),
    ModelConfig(Provider.OPENAI, "gpt-5.5",                has_search=True),
]


# ── Системный промпт ──────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are an expert LinkedIn content creator AND a senior infographic designer specializing in AI, ML, and software engineering topics.

Your task has THREE outputs:
1. Research the topic {search_instruction}
2. Write a high-quality LinkedIn post in ENGLISH
3. Design {min_imgs}-{max_imgs} INFOGRAPHIC prompts that will be rendered by OpenAI gpt-image-1
   (which IS GOOD AT TEXT INSIDE IMAGES — use that capability!)

Return ONLY a JSON object with two fields: "post" and "image_prompts" (list of strings).

═══════════════════════════════════════════════════════════════════════════
LINKEDIN POST REQUIREMENTS
═══════════════════════════════════════════════════════════════════════════
- Language: ENGLISH
- Length: 1200–2000 characters
- Structure:
  • Line 1-2: Strong hook — a surprising fact, counterintuitive insight, or bold claim
  • Empty line
  • 3-5 short paragraphs with key insights (specific numbers, tool names, paper titles)
  • Each insight on its own line, prefixed with a relevant emoji
  • Empty line
  • 1-2 sentence closing thought / question to the reader
  • Empty line
  • 5-7 relevant hashtags
- Style: authoritative but conversational. NO corporate speak, NO fluff, NO generic claims.
- Include CONCRETE data points and proper nouns (tool names, paper titles, GitHub repos, %, X faster/cheaper)
- NO markdown (no **bold**, no #headers) — LinkedIn renders plain text only

═══════════════════════════════════════════════════════════════════════════
IMAGE_PROMPTS — INFOGRAPHIC SLIDE DESIGN
═══════════════════════════════════════════════════════════════════════════
Design clean infographic SLIDES that illustrate the post content.
Think "premium LinkedIn carousel slide", NOT "cyberpunk neural network art".

EACH IMAGE_PROMPT MUST INCLUDE:
1. EXPLICIT TITLE TEXT at the top (use quotes in the prompt)
2. 3-5 LABELED ELEMENTS (named cards / numbered items / bars) — NEVER more than 5
3. CONCRETE LABELS (2-5 words) taken from actual post content
4. ONE KEY METRIC OR NUMBER per element where applicable
5. A visual structure: timeline / comparison / hierarchy / numbered grid / bar chart

VISUAL STYLE:
- Dark navy background (#0a0e1a), bright accents: cyan, orange, white
- Lots of negative space — uncluttered, breathable
- Crisp sans-serif typography (Inter/SF Pro style)
- Subtle icons next to labels (one tiny icon per item)
- 16:9 horizontal layout for LinkedIn feed
- NO photorealistic, NO 3D renders, NO cyberpunk glow, NO abstract neural-network mesh
- Looks like it was made in Figma by a senior designer

ANTI-PATTERNS:
- 8+ items on one slide → split into 2 cleaner slides
- Long sentences (max 5 words per label)
- Decorative art that doesn't carry information

NUMBER OF IMAGES ({min_imgs}-{max_imgs}):
- 1: single dominant idea or one comparison
- 2: two angles (problem + solution, before/after, overview + tools list)
- 3+: only if post has clearly separable sections with own data

EXAMPLE IMAGE_PROMPT:
"Clean modern infographic slide, 16:9, dark navy background (#0a0e1a).
Title (large white sans-serif): 'Top 4 LLM Inference Optimizations'.
Subtitle (muted gray): 'Production benchmarks, 2026'.
Four horizontal cards in a 2x2 grid, rounded corners, subtle borders.
Card 1 (cyan accent, chip icon): 'vLLM PagedAttention' / '24× throughput'
Card 2 (orange accent, lightning icon): 'FlashAttention-3' / '75% GPU util'
Card 3 (cyan accent, rocket icon): 'Speculative Decoding' / '2.5× faster'
Card 4 (orange accent, compress icon): 'KV-cache 8-bit' / '4× memory'
Lots of negative space. Crisp typography. No background patterns, no glow."

═══════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT — STRICT JSON ONLY
═══════════════════════════════════════════════════════════════════════════
{{
  "post": "...",
  "image_prompts": ["...", "..."]
}}
"""


def _build_system_prompt() -> str:
    max_imgs = max(1, min(4, settings.max_images_per_post))
    return SYSTEM_PROMPT_TEMPLATE.format(
        min_imgs=1,
        max_imgs=max_imgs,
        search_instruction="with web search (recent news, benchmarks, papers, GitHub repos, real-world numbers)",
    )


# ── Определение «временно недоступна» ────────────────────────────────────────

def _is_unavailable(exc: Exception) -> bool:
    """True если это временная перегрузка/недоступность модели — можно пробовать следующую."""
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "503", "unavailable", "overload", "high demand",
        "try again later", "temporarily", "capacity",
    ))


# ── Генераторы для каждого провайдера ────────────────────────────────────────

_USER_MSG = (
    "Topic for LinkedIn post: {topic}\n\n"
    "Use web search to research this topic thoroughly — find recent news, benchmarks, "
    "papers, GitHub repos, specific numbers and real-world results. "
    "Then write the LinkedIn post AND design infographic slide prompts. Return JSON."
)


def _run_gemini(topic: str, model: ModelConfig) -> dict:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY не задан в .env")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model.model_id,
        contents=_USER_MSG.format(topic=topic),
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(),
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=1.0,
        ),
    )
    return _parse_response((response.text or "").strip())


def _run_openai(topic: str, model: ModelConfig) -> dict:
    """
    Использует OpenAI Responses API с инструментом web_search_preview.
    Это даёт модели доступ к актуальным данным из интернета (через Bing),
    аналогично тому как Gemini использует Google Search.
    """
    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не задан в .env")

    client = OpenAI(api_key=api_key, timeout=180.0)

    response = client.responses.create(
        model=model.model_id,
        instructions=_build_system_prompt(),
        input=_USER_MSG.format(topic=topic),
        tools=[{"type": "web_search_preview"}],
        temperature=1.0,
    )
    raw = (response.output_text or "").strip()
    return _parse_response(raw)


_PROVIDER_FN: dict[Provider, Callable] = {
    Provider.GEMINI: _run_gemini,
    Provider.OPENAI: _run_openai,
}


# ── Главная публичная функция ─────────────────────────────────────────────────

def generate_post_content(topic: str) -> dict:
    """
    Пробует модели из TEXT_MODEL_CHAIN по порядку.
    Переключается на следующую только при ошибках недоступности (503 / overload).
    Любые другие ошибки (4xx, неверный ключ, quota) — пробрасывает сразу.
    """
    last_exc: Exception | None = None

    for model in TEXT_MODEL_CHAIN:
        log.info("Пробую %s / %s для темы: %r", model.provider.value, model.model_id, topic)
        try:
            result = _PROVIDER_FN[model.provider](topic, model)
            log.info("Успех: %s / %s (%d символов поста, %d картинок)",
                     model.provider.value, model.model_id,
                     len(result["post"]), len(result.get("image_prompts", [])))
            return result

        except Exception as exc:
            if _is_unavailable(exc):
                log.warning("Модель %s/%s недоступна (перегрузка), пробую следующую: %s",
                            model.provider.value, model.model_id, exc)
                last_exc = exc
                continue
            # Любая другая ошибка — пробрасываем немедленно
            log.exception("Ошибка в %s/%s (не связана с доступностью)",
                          model.provider.value, model.model_id)
            raise

    raise RuntimeError(
        f"Все модели недоступны. Последняя ошибка: {last_exc}"
    ) from last_exc


# ── Парсинг JSON ──────────────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict:
    """Извлекает JSON из ответа (терпим к markdown-обёртке и тексту после JSON)."""
    if "```" in raw:
        inner_start = raw.find("```") + 3
        inner_end = raw.rfind("```")
        if inner_end > inner_start:
            raw = raw[inner_start:inner_end]
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]
            raw = raw.strip()

    obj_start = raw.find("{")
    if obj_start == -1:
        log.error("JSON-объект не найден в ответе. Полный ответ:\n%s", raw)
        raise RuntimeError(f"Модель не вернула JSON. Ответ начинается с: {raw[:200]!r}")

    try:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(raw, obj_start)
    except json.JSONDecodeError as exc:
        log.error(
            "JSON parse error.\nПозиция: %s\nКонтекст: %r\nПолный ответ:\n%s",
            exc, raw[max(0, exc.pos - 40): exc.pos + 40], raw,
        )
        raise RuntimeError(
            f"JSON parse error: {exc}\n"
            f"Контекст: ...{raw[max(0, exc.pos - 40):exc.pos + 40]}..."
        ) from exc

    if "post" not in data:
        raise RuntimeError(f"JSON без поля 'post'. Получено: {list(data.keys())}")

    # Нормализуем image_prompts
    if "image_prompts" not in data:
        if "image_prompt" in data and data["image_prompt"]:
            data["image_prompts"] = [data["image_prompt"]]
            del data["image_prompt"]
        else:
            data["image_prompts"] = []

    prompts = data["image_prompts"]
    if not isinstance(prompts, list):
        raise RuntimeError(f"image_prompts должен быть list, получили: {type(prompts).__name__}")

    prompts = [p.strip() for p in prompts if isinstance(p, str) and p.strip()]
    max_imgs = max(1, min(4, settings.max_images_per_post))
    if len(prompts) > max_imgs:
        log.info("Обрезаю список картинок: %d → %d", len(prompts), max_imgs)
        prompts = prompts[:max_imgs]
    data["image_prompts"] = prompts

    log.info("Пост готов (%d символов, %d image_prompts)", len(data["post"]), len(prompts))
    for i, p in enumerate(prompts, 1):
        log.debug("Image prompt #%d: %s…", i, p[:120].replace("\n", " "))

    return data
