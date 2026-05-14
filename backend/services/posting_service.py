"""
posting_service.py — оркестрация генерации и публикации, разбитая на явные фазы.

Фазы (вызываются отдельно из bot handlers):
  Phase 1 — generate_text(topic)          → post_text + image_prompts  (без списания)
  Phase 2 — generate_images(prompts)      → image_paths               (без списания)
  Phase 3 — publish(...)                  → post_id                   (−$1.00)

  Extra  — charge_for_regen(tg_id)        → new_balance               (−$0.50)

Подсказка темы из интересов юзера — suggest_topic_for_user().
"""

import asyncio
import json
import random
from typing import Optional

from backend.config import settings
from backend.db import crud
from backend.db.models import Generation, GenerationStatus, User
from backend.db.session import session_scope
from backend.generator import generate_post_content
from backend.images import generate_images as _generate_images
from backend.linkedin import LinkedInClient
from backend.logger import get_logger
from backend.services.billing_service import InsufficientFunds, charge_for_generation, get_balance
from backend.services.interests import label

log = get_logger(__name__)


# ── Phase 1: только текст поста + image_prompts ───────────────────────────────

async def generate_text(topic: str) -> dict:
    """
    Генерирует текст поста и список image_prompts.
    Без БД-записей, без списания денег.

    Returns:
        {"post": str, "image_prompts": list[str]}
    """
    log.info("Phase 1: генерация текста | topic=%r", topic)
    content = await asyncio.to_thread(generate_post_content, topic)
    log.info("Phase 1: готово (%d символов, %d промптов картинок)",
             len(content["post"]), len(content.get("image_prompts", [])))
    return content


# ── Phase 2: только картинки ─────────────────────────────────────────────────

async def generate_images(
    image_prompts: list[str],
    aspect_ratio: str = "16:9",
) -> list[str]:
    """
    Параллельно генерирует N картинок.
    Без БД-записей, без списания денег.

    Returns:
        list путей к PNG
    """
    log.info("Phase 2: генерация %d картинок", len(image_prompts))
    paths = await _generate_images(image_prompts, aspect_ratio=aspect_ratio)
    log.info("Phase 2: готово (%d из %d картинок)", len(paths), len(image_prompts))
    return paths


# ── Phase 3: публикация + списание $1 ────────────────────────────────────────

async def publish(
    *,
    tg_id: int,
    topic: str,
    post_text: str,
    image_prompts: list[str],
    image_paths: list[str],
) -> tuple[Optional[str], int]:
    """
    Публикует готовый пост в LinkedIn, создаёт запись в БД, списывает COST_PER_POST_CENTS.

    Returns:
        (linkedin_post_id, new_balance_cents)

    Raises:
        InsufficientFunds — недостаточно средств
        RuntimeError     — LinkedIn не привязан или другая ошибка
    """
    cost_cents = settings.cost_per_post_cents

    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            raise RuntimeError(f"User tg={tg_id} не найден")
        if user.balance_cents < cost_cents:
            raise InsufficientFunds(
                f"Нужно ${cost_cents/100:.2f}, на балансе ${user.balance_cents/100:.2f}"
            )
        if not user.is_authorized:
            raise RuntimeError("LinkedIn не привязан. Нажми «Связать LinkedIn» в /start")

        access_token = user.linkedin_access_token
        person_urn = user.linkedin_person_urn
        gen = await crud.create_generation(session, user, topic)
        gen_id = gen.id

    log.info("Phase 3: публикация | user=%s gen_id=%s images=%d", tg_id, gen_id, len(image_paths))

    if settings.mock_linkedin:
        linkedin_post_id = f"mock-{gen_id}-{random.randint(1000, 9999)}"
        log.info("MOCK publish | post_id=%s", linkedin_post_id)
    else:
        try:
            client = LinkedInClient(access_token=access_token, person_urn=person_urn)
            linkedin_post_id = await asyncio.to_thread(client.publish, post_text, image_paths)
        except Exception as e:
            log.exception("Publish failed | user=%s gen_id=%s", tg_id, gen_id)
            async with session_scope() as session:
                gen = await session.get(Generation, gen_id)
                if gen:
                    await crud.update_generation(
                        session, gen,
                        post_text=post_text,
                        image_prompts_json=json.dumps(image_prompts),
                        image_paths_json=json.dumps(image_paths),
                        status=GenerationStatus.FAILED,
                        error=str(e)[:1000],
                    )
            raise

    new_balance = await charge_for_generation(tg_id, cost_cents)

    async with session_scope() as session:
        gen = await session.get(Generation, gen_id)
        await crud.update_generation(
            session, gen,
            post_text=post_text,
            image_prompts_json=json.dumps(image_prompts),
            image_paths_json=json.dumps(image_paths),
            linkedin_post_id=linkedin_post_id,
            cost_cents=cost_cents,
            status=GenerationStatus.PUBLISHED,
        )

    log.info("Phase 3: готово | post_id=%s balance=%d", linkedin_post_id, new_balance)
    return linkedin_post_id, new_balance


# ── Перегенерация текста (−$0.50) ─────────────────────────────────────────────

async def charge_for_regen(tg_id: int) -> int:
    """
    Списывает REGEN_TEXT_CENTS (по умолчанию $0.50) за перегенерацию текста.

    Returns:
        Новый баланс в центах.

    Raises:
        InsufficientFunds
    """
    cost = settings.regen_text_cents
    balance = await get_balance(tg_id)
    if balance < cost:
        raise InsufficientFunds(
            f"Нужно ${cost/100:.2f} для перегенерации, на балансе ${balance/100:.2f}"
        )
    new_balance = await charge_for_generation(tg_id, cost)
    log.info("Перегенерация текста списана | user=%s -%d cents → %d cents",
             tg_id, cost, new_balance)
    return new_balance


# ── Подсказка темы ────────────────────────────────────────────────────────────

_TOPIC_TEMPLATES = [
    "latest breakthroughs in {topic}",
    "underrated tools for {topic} in 2026",
    "biggest production challenges of {topic}",
    "what's new in {topic} this month",
    "counterintuitive lessons from {topic}",
    "hidden costs of {topic} in production",
    "why most engineers get {topic} wrong",
]


async def suggest_topic_for_user(user: User) -> str:
    interests = user.interests or ["ai_agents"]
    interest = random.choice(interests)
    template = random.choice(_TOPIC_TEMPLATES)
    nice_label = label(interest).split(" ", 1)[-1]
    return template.format(topic=nice_label)
