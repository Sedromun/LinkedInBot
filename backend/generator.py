"""
generator.py — генерация поста через Gemini 2.5 Flash + встроенный Google Search.

Gemini сам решает, что и сколько раз искать — встроенный Google Search.
"""

import json
import os

from google import genai
from google.genai import types

from backend.logger import get_logger
from backend.proxy import configure_env_proxy

configure_env_proxy()  # применяем до создания genai.Client

log = get_logger(__name__)

# ── Системный промпт ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert LinkedIn content creator specializing in AI, ML, and software engineering topics.

Your task:
1. Use Google Search to research the given topic thoroughly.
   Look for: recent news, benchmarks, open-source tools, papers, real-world results.
2. After research, write a high-quality LinkedIn post in ENGLISH.
3. Return a JSON object with exactly two fields: "post" and "image_prompt".

LinkedIn post requirements:
- Language: ENGLISH
- Length: 1200–2000 characters (optimal engagement)
- Structure:
  • Line 1-2: Strong hook — a surprising fact, counterintuitive insight, or bold statement
    (must make people stop scrolling!)
  • Empty line
  • 3–5 short paragraphs with key insights (use specific numbers, names, tools)
  • Each insight on a new line, preceded by a relevant emoji
  • Empty line
  • Closing thought / call-to-action (1–2 sentences)
  • Empty line
  • 5–7 relevant hashtags
- Style: authoritative but conversational, no corporate speak, no fluff
- Include specific data points, tool names, paper titles, or GitHub repos you found
- NO markdown formatting (no **bold**, no #headers) — LinkedIn renders plain text only

image_prompt requirements:
- Detailed prompt for Imagen (English)
- Style: modern tech illustration, dark background, glowing elements
- Must visually represent the topic
- No text in the image
- Example: "A futuristic visualization of neural network inference optimization, glowing blue circuits on dark background, abstract transformer architecture with speed lines, modern tech illustration style"

IMPORTANT: Respond ONLY with valid JSON. No explanation before or after.
Format:
{
  "post": "...",
  "image_prompt": "..."
}"""


# ── Генерация контента ────────────────────────────────────────────────────────

def generate_post_content(topic: str) -> dict:
    """
    Исследует тему через Gemini 2.5 Flash + Google Search и генерирует пост.

    Returns:
        dict с ключами 'post' и 'image_prompt'
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Не задан GOOGLE_API_KEY в .env")

    client = genai.Client(api_key=api_key)

    log.info("Запускаю gemini-3.1-flash-lite для темы: %r", topic)

    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=(
                f"Topic for LinkedIn post: {topic}\n\n"
                "Research this topic thoroughly using Google Search, find recent data, "
                "specific numbers, tools and real-world cases. "
                "Then write an excellent post in English and return JSON."
            ),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=1.0,
            ),
        )
    except Exception:
        log.exception("Ошибка при обращении к Gemini API")
        raise

    raw_text = response.text.strip()
    log.debug("Ответ Gemini (%d символов):\n%s", len(raw_text), raw_text[:500])

    return _parse_response(raw_text)


# ── Парсинг JSON из ответа ────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict:
    """
    Извлекает JSON из текста Gemini.

    Использует raw_decode — корректно обрабатывает случаи когда модель
    пишет что-то после закрывающей скобки JSON.
    """
    # 1. Убираем markdown-обёртку ```json ... ```
    if "```" in raw:
        inner_start = raw.find("```") + 3
        inner_end = raw.rfind("```")
        if inner_end > inner_start:
            raw = raw[inner_start:inner_end]
            # убираем "json" после открывающих кавычек
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]
            raw = raw.strip()

    # 2. Находим начало JSON-объекта
    obj_start = raw.find("{")
    if obj_start == -1:
        log.error("JSON-объект не найден в ответе Gemini. Полный ответ:\n%s", raw)
        raise RuntimeError(
            f"Gemini не вернул JSON. Ответ начинается с: {raw[:200]!r}"
        )

    # 3. raw_decode парсит первый валидный JSON и игнорирует всё после него
    try:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(raw, obj_start)
    except json.JSONDecodeError as exc:
        log.error(
            "Не удалось распарсить JSON из ответа Gemini.\n"
            "Позиция ошибки: %s\n"
            "Фрагмент вокруг ошибки: %r\n"
            "Полный ответ:\n%s",
            exc,
            raw[max(0, exc.pos - 40): exc.pos + 40],
            raw,
        )
        raise RuntimeError(
            f"JSON parse error от Gemini: {exc}\n"
            f"Контекст: ...{raw[max(0, exc.pos-40):exc.pos+40]}..."
        ) from exc

    # 4. Проверяем наличие нужных полей
    missing = [f for f in ("post", "image_prompt") if f not in data]
    if missing:
        log.error("В JSON отсутствуют поля %s. Получено: %s", missing, list(data.keys()))
        raise RuntimeError(
            f"Gemini вернул JSON без полей {missing}. Есть только: {list(data.keys())}"
        )

    log.info("Пост сгенерирован (%d символов), промпт картинки: %r",
             len(data["post"]), data["image_prompt"][:80])
    return data
