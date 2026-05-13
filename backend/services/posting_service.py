"""
posting_service.py — оркестрация полного цикла генерации и публикации.

Пайплайн для одного юзера:
  1. Проверить баланс (без списания)
  2. Создать Generation(PENDING)
  3. Gemini: текст поста + N image_prompts
  4. gpt-image-1: N картинок параллельно
  5. LinkedIn: публикация (или mock)
  6. Списать деньги (только при успехе публикации)
  7. Обновить Generation
"""

import asyncio
import json
import random
from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings
from backend.db import crud
from backend.db.models import Generation, GenerationStatus, User
from backend.db.session import session_scope
from backend.generator import generate_post_content
from backend.images import generate_images
from backend.linkedin import LinkedInClient
from backend.logger import get_logger
from backend.services.billing_service import InsufficientFunds, charge_for_generation
from backend.services.interests import label

log = get_logger(__name__)


@dataclass
class GenerationResult:
    generation_id:    int
    post_text:        str
    image_prompts:    list[str]
    image_paths:      list[str]                 # сгенерированные PNG (могут быть < image_prompts если что-то упало)
    linkedin_post_id: Optional[str]
    published:        bool
    cost_cents:       int
    new_balance:      int


# ── Подсказка темы из интересов ──────────────────────────────────────────────

_TOPIC_TEMPLATES = [
    "latest breakthroughs in {topic}",
    "underrated tools for {topic} in 2026",
    "biggest production challenges of {topic}",
    "what's new in {topic} this month",
    "counterintuitive lessons from {topic}",
]


async def suggest_topic_for_user(user: User) -> str:
    interests = user.interests or ["ai_agents"]
    interest = random.choice(interests)
    template = random.choice(_TOPIC_TEMPLATES)
    nice_label = label(interest).split(" ", 1)[-1]
    return template.format(topic=nice_label)


# ── Главный pipeline ─────────────────────────────────────────────────────────

async def run_pipeline(
    *,
    tg_id: int,
    topic: str,
    aspect_ratio: str = "16:9",
    publish: bool = True,
) -> GenerationResult:
    cost_cents = settings.cost_per_post_cents

    # ── Снапшот юзера + создание записи ─────────────────────────────────────
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            raise RuntimeError(f"User tg={tg_id} не найден")
        if user.balance_cents < cost_cents:
            raise InsufficientFunds(
                f"Нужно ${cost_cents / 100:.2f}, на балансе ${user.balance_cents / 100:.2f}"
            )
        if publish and not user.is_authorized:
            raise RuntimeError("LinkedIn не привязан. Нажми «Связать LinkedIn» в /start")

        gen = await crud.create_generation(session, user, topic)
        gen_id = gen.id
        access_token = user.linkedin_access_token
        person_urn = user.linkedin_person_urn

    log.info("Pipeline start | user=%s gen_id=%s topic=%r", tg_id, gen_id, topic)

    # ── Шаг 1: текст + промпты картинок ─────────────────────────────────────
    try:
        content = await asyncio.to_thread(generate_post_content, topic)
        post_text: str = content["post"]
        image_prompts: list[str] = content.get("image_prompts", [])
    except Exception as e:
        log.exception("Text generation failed | user=%s gen_id=%s", tg_id, gen_id)
        await _mark_failed(gen_id, f"text: {e}")
        raise

    # Сохраняем промпты сразу — на случай падения генерации картинок
    await _save_partial(gen_id, post_text=post_text, image_prompts_json=json.dumps(image_prompts))

    # ── Шаг 2: параллельная генерация картинок ──────────────────────────────
    image_paths: list[str] = []
    if image_prompts:
        try:
            image_paths = await generate_images(image_prompts, aspect_ratio=aspect_ratio)
        except Exception as e:
            log.warning("Image gen полностью упала (продолжаем без картинок) | user=%s: %s", tg_id, e)
            image_paths = []
        if not image_paths:
            log.warning("Ни одной картинки не сгенерировалось | user=%s gen_id=%s", tg_id, gen_id)

    # ── Шаг 3: публикация в LinkedIn ────────────────────────────────────────
    linkedin_post_id: Optional[str] = None
    if publish and access_token and person_urn:
        if settings.mock_linkedin:
            linkedin_post_id = f"mock-{gen_id}-{random.randint(1000, 9999)}"
            log.info("MOCK publish | user=%s gen_id=%s fake_post_id=%s",
                     tg_id, gen_id, linkedin_post_id)
        else:
            try:
                client = LinkedInClient(access_token=access_token, person_urn=person_urn)
                linkedin_post_id = await asyncio.to_thread(
                    client.publish, post_text, image_paths,
                )
            except Exception as e:
                log.exception("Publish failed | user=%s gen_id=%s", tg_id, gen_id)
                await _mark_failed(
                    gen_id,
                    f"publish: {e}",
                    post_text=post_text,
                    image_prompts_json=json.dumps(image_prompts),
                    image_paths_json=json.dumps(image_paths),
                )
                raise

    # ── Шаг 4: списание + финализация ───────────────────────────────────────
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
            status=GenerationStatus.PUBLISHED if publish else GenerationStatus.GENERATED,
        )

    log.info(
        "Pipeline done | user=%s gen_id=%s post_id=%s images=%d balance=%d",
        tg_id, gen_id, linkedin_post_id, len(image_paths), new_balance,
    )

    return GenerationResult(
        generation_id=gen_id,
        post_text=post_text,
        image_prompts=image_prompts,
        image_paths=image_paths,
        linkedin_post_id=linkedin_post_id,
        published=bool(linkedin_post_id),
        cost_cents=cost_cents,
        new_balance=new_balance,
    )


# ── Вспомогалки ──────────────────────────────────────────────────────────────

async def _save_partial(gen_id: int, **fields) -> None:
    """Сохранить промежуточное состояние Generation (без смены статуса)."""
    async with session_scope() as session:
        gen = await session.get(Generation, gen_id)
        if gen:
            await crud.update_generation(session, gen, **fields)


async def _mark_failed(gen_id: int, error: str, **extra) -> None:
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
