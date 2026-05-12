"""
posting_service.py — оркестрация полного цикла генерации и публикации
для конкретного юзера из БД.

Запускается в executor через asyncio.to_thread(), т.к. наш генератор/LinkedIn-клиент синхронные.
"""

import asyncio
import random
from dataclasses import dataclass
from typing import Optional

from backend.config import settings
from backend.db import crud
from backend.db.models import Generation, GenerationStatus, User
from backend.db.session import session_scope
from backend.generator import generate_post_content
from backend.images import generate_image
from backend.linkedin import LinkedInClient
from backend.logger import get_logger
from backend.services.billing_service import InsufficientFunds, charge_for_generation
from backend.services.interests import label

log = get_logger(__name__)


@dataclass
class GenerationResult:
    generation_id:  int
    post_text:      str
    image_prompt:   str
    image_path:     Optional[str]
    linkedin_post_id: Optional[str]
    published:      bool
    cost_cents:     int
    new_balance:    int


# ── Подсказка темы из интересов ──────────────────────────────────────────────

_TOPIC_TEMPLATES = [
    "latest breakthroughs in {topic}",
    "underrated tools for {topic} in 2026",
    "biggest production challenges of {topic}",
    "what's new in {topic} this month",
    "counterintuitive lessons from {topic}",
]


async def suggest_topic_for_user(user: User) -> str:
    """Случайно подбирает тему из интересов юзера."""
    interests = user.interests or ["ai_agents"]
    interest = random.choice(interests)
    template = random.choice(_TOPIC_TEMPLATES)
    nice_label = label(interest).split(" ", 1)[-1]  # отрезаем эмодзи
    return template.format(topic=nice_label)


# ── Главный pipeline ─────────────────────────────────────────────────────────

async def run_pipeline(
    *,
    tg_id: int,
    topic: str,
    aspect_ratio: str = "16:9",
    publish: bool = True,
) -> GenerationResult:
    """
    Полный цикл:
      1. Проверить баланс (но НЕ списывать — пока не получится сгенерить + опубликовать)
      2. Создать запись Generation(status=PENDING)
      3. Сгенерировать текст + картинку
      4. Опубликовать в LinkedIn (если publish=True)
      5. Списать деньги (только при успехе)
      6. Обновить запись Generation
    """
    cost_cents = settings.cost_per_post_cents

    # Снапшот юзера и создание записи
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            raise RuntimeError(f"User tg={tg_id} не найден")
        if user.balance_cents < cost_cents:
            raise InsufficientFunds(
                f"Нужно ${cost_cents/100:.2f}, на балансе ${user.balance_cents/100:.2f}"
            )
        if publish and not user.is_authorized:
            raise RuntimeError("LinkedIn не привязан. Нажми «Связать LinkedIn» в /start")

        gen = await crud.create_generation(session, user, topic)
        gen_id = gen.id
        access_token = user.linkedin_access_token
        person_urn   = user.linkedin_person_urn

    log.info("Pipeline start | user=%s gen_id=%s topic=%r", tg_id, gen_id, topic)

    # ── Генерация (offload в thread, т.к. синхронный SDK) ───────────────────
    try:
        content = await asyncio.to_thread(generate_post_content, topic)
        post_text    = content["post"]
        image_prompt = content["image_prompt"]
    except Exception as e:
        log.exception("Generation failed | user=%s gen_id=%s", tg_id, gen_id)
        await _mark_failed(gen_id, f"text: {e}")
        raise

    # ── Картинка ────────────────────────────────────────────────────────────
    image_path: Optional[str] = None
    try:
        image_path = await asyncio.to_thread(generate_image, image_prompt, aspect_ratio)
    except Exception as e:
        log.warning("Image gen failed (продолжаем без картинки) | user=%s: %s", tg_id, e)

    # ── Публикация ───────────────────────────────────────────────────────────
    linkedin_post_id: Optional[str] = None
    if publish and access_token and person_urn:
        if settings.mock_linkedin:
            # DEV: имитируем публикацию
            linkedin_post_id = f"mock-{gen_id}-{random.randint(1000, 9999)}"
            log.info("MOCK publish | user=%s gen_id=%s fake_post_id=%s", tg_id, gen_id, linkedin_post_id)
        else:
            try:
                client = LinkedInClient(access_token=access_token, person_urn=person_urn)
                linkedin_post_id = await asyncio.to_thread(client.publish, post_text, image_path)
            except Exception as e:
                log.exception("Publish failed | user=%s gen_id=%s", tg_id, gen_id)
                await _mark_failed(gen_id, f"publish: {e}", post_text=post_text,
                                   image_prompt=image_prompt, image_path=image_path)
                raise

    # ── Списание + финализация ──────────────────────────────────────────────
    new_balance = await charge_for_generation(tg_id, cost_cents)

    async with session_scope() as session:
        gen = await session.get(Generation, gen_id)
        await crud.update_generation(
            session, gen,
            post_text=post_text,
            image_prompt=image_prompt,
            image_path=image_path,
            linkedin_post_id=linkedin_post_id,
            cost_cents=cost_cents,
            status=GenerationStatus.PUBLISHED if publish else GenerationStatus.GENERATED,
        )

    log.info("Pipeline done | user=%s gen_id=%s post_id=%s balance=%d",
             tg_id, gen_id, linkedin_post_id, new_balance)

    return GenerationResult(
        generation_id=gen_id,
        post_text=post_text,
        image_prompt=image_prompt,
        image_path=image_path,
        linkedin_post_id=linkedin_post_id,
        published=bool(linkedin_post_id),
        cost_cents=cost_cents,
        new_balance=new_balance,
    )


async def _mark_failed(gen_id: int, error: str, **extra) -> None:
    """Сохранить статус FAILED + опционально промежуточные поля."""
    async with session_scope() as session:
        gen = await session.get(Generation, gen_id)
        if not gen:
            return
        await crud.update_generation(
            session, gen,
            status=GenerationStatus.FAILED,
            error=error[:1000],
            **extra,
        )
