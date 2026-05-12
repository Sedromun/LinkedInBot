"""
Хендлеры команд и callback-кнопок.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from backend.bot import keyboards, messages
from backend.bot.deps import get_bot
from backend.config import settings
from backend.db import crud
from backend.db.session import session_scope
from backend.logger import get_logger
from backend.services import billing_service, oauth_service, posting_service
from backend.services.billing_service import InsufficientFunds
from backend.services.interests import INTERESTS, label

log = get_logger(__name__)
router = Router()


# ── FSM состояния ────────────────────────────────────────────────────────────

class GenerateStates(StatesGroup):
    waiting_for_topic = State()


class TopupStates(StatesGroup):
    waiting_for_custom_amount = State()


# ── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    tg_user = message.from_user
    async with session_scope() as session:
        user, created = await crud.get_or_create_user(
            session,
            tg_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            initial_balance_cents=settings.initial_balance_cents,
        )
        await session.flush()
        authorized = user.is_authorized
        balance_usd = user.balance_usd

    if created:
        log.info("New user registered | tg_id=%s username=%s", tg_user.id, tg_user.username)

    cost_usd = settings.cost_per_post_cents / 100
    posts = int(balance_usd / cost_usd) if cost_usd > 0 else 0

    await message.answer(
        messages.WELCOME.format(
            name=tg_user.first_name or "друг",
            balance=f"{balance_usd:.2f}",
            cost=f"{cost_usd:.2f}",
            posts=posts,
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_menu(authorized=authorized),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — главное меню\n"
        "/generate — сгенерировать пост\n"
        "/interests — выбрать темы\n"
        "/balance — баланс\n"
        "/settings — настройки\n"
        "/notifications — вкл/выкл ежедневные напоминания",
    )


# ── OAuth flow ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "oauth_start")
async def cb_oauth_start(callback: CallbackQuery) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            await callback.message.answer("Сначала отправь /start.")
            return
        if user.is_authorized:
            await callback.message.answer(messages.OAUTH_ALREADY_DONE)
            return

    # DEV-режим: моментально мокаем привязку, без редиректа
    if settings.mock_linkedin:
        await oauth_service.mock_authorize(tg_id)
        await callback.message.answer(messages.OAUTH_SUCCESS_MOCK, parse_mode="HTML")
        return

    url = await oauth_service.start_oauth(user)
    await callback.message.answer(
        messages.OAUTH_INSTRUCTIONS.format(url=url),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ── Interests ─────────────────────────────────────────────────────────────────

@router.message(Command("interests"))
@router.callback_query(F.data == "interests")
async def show_interests(event: Message | CallbackQuery) -> None:
    tg_id = event.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        selected = user.interests if user else []

    text = messages.CHOOSE_INTERESTS
    kb = keyboards.interests_keyboard(selected)
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("int_toggle:"))
async def cb_interest_toggle(callback: CallbackQuery) -> None:
    slug = callback.data.split(":", 1)[1]
    tg_id = callback.from_user.id

    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            await callback.answer("Сначала /start", show_alert=True)
            return
        interests = user.interests
        if slug in interests:
            interests.remove(slug)
        else:
            interests.append(slug)
        user.interests = interests
        new_selected = list(interests)

    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboards.interests_keyboard(new_selected))
    except Exception:
        pass


@router.callback_query(F.data == "int_done")
async def cb_interest_done(callback: CallbackQuery) -> None:
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        interests = user.interests if user else []

    if not interests:
        await callback.answer(messages.INTERESTS_EMPTY, show_alert=True)
        return

    labels = ", ".join(label(s) for s in interests)
    await callback.answer()
    await callback.message.answer(
        messages.INTERESTS_SAVED.format(labels=labels),
        parse_mode="HTML",
    )


# ── Balance / Topup ──────────────────────────────────────────────────────────

@router.message(Command("balance"))
@router.callback_query(F.data == "balance")
async def show_balance(event: Message | CallbackQuery) -> None:
    tg_id = event.from_user.id
    balance_cents = await billing_service.get_balance(tg_id)
    cost_cents = settings.cost_per_post_cents
    posts = balance_cents // cost_cents if cost_cents else 0
    text = messages.BALANCE_INFO.format(
        balance=balance_cents / 100,
        cost=cost_cents / 100,
        posts=posts,
    )
    kb = keyboards.balance_keyboard()
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "topup_menu")
async def cb_topup_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(messages.TOPUP_PROMPT, reply_markup=keyboards.topup_keyboard())


@router.callback_query(F.data.startswith("topup:"))
async def cb_topup(callback: CallbackQuery) -> None:
    amount_cents = int(callback.data.split(":", 1)[1])
    new_balance = await billing_service.topup_mock(callback.from_user.id, amount_cents)
    await callback.answer()
    await callback.message.answer(
        messages.TOPUP_SUCCESS.format(amount=amount_cents / 100, balance=new_balance / 100),
        parse_mode="HTML",
    )


# ── Generate ──────────────────────────────────────────────────────────────────

@router.message(Command("generate"))
@router.callback_query(F.data == "generate")
async def cmd_generate(event: Message | CallbackQuery, state: FSMContext) -> None:
    tg_id = event.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user or not user.is_authorized:
            text = messages.NOT_AUTHORIZED
            if isinstance(event, CallbackQuery):
                await event.answer()
                await event.message.answer(text)
            else:
                await event.answer(text)
            return

    await state.set_state(GenerateStates.waiting_for_topic)
    text = messages.GENERATE_PROMPT
    kb = keyboards.generate_topic_keyboard()
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "gen_auto_topic")
async def cb_gen_auto(callback: CallbackQuery, state: FSMContext) -> None:
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            await callback.answer("Сначала /start", show_alert=True)
            return
        if not user.interests:
            await callback.answer("Сначала выбери интересы: /interests", show_alert=True)
            return
        topic = await posting_service.suggest_topic_for_user(user)

    await callback.answer()
    await state.clear()
    await _run_generation(callback.message, tg_id, topic)


@router.message(GenerateStates.waiting_for_topic)
async def on_topic_received(message: Message, state: FSMContext) -> None:
    topic = (message.text or "").strip()
    if len(topic) < 3:
        await message.answer("Тема слишком короткая. Попробуй ещё раз или /cancel.")
        return
    await state.clear()
    await _run_generation(message, message.from_user.id, topic)


async def _run_generation(reply_to: Message, tg_id: int, topic: str) -> None:
    """Запускает pipeline, шлёт уведомление с прогрессом и результатом."""
    progress = await reply_to.answer(
        messages.GENERATING.format(topic=topic),
        parse_mode="HTML",
    )

    try:
        result = await posting_service.run_pipeline(
            tg_id=tg_id, topic=topic, aspect_ratio="16:9", publish=True,
        )
    except InsufficientFunds as e:
        balance = await billing_service.get_balance(tg_id)
        await reply_to.answer(
            messages.INSUFFICIENT_FUNDS.format(
                need=settings.cost_per_post_cents / 100,
                balance=balance / 100,
            ),
            parse_mode="HTML",
        )
        return
    except Exception as e:
        log.exception("Generation pipeline failed for user=%s", tg_id)
        await reply_to.answer(
            messages.GENERATION_FAILED.format(error=str(e)[:300]),
            parse_mode="HTML",
        )
        return

    # Шлём картинку (если есть) + текст
    if result.image_path:
        try:
            await reply_to.answer_photo(
                FSInputFile(result.image_path),
                caption=result.post_text[:1024],  # caption-лимит TG
            )
            if len(result.post_text) > 1024:
                await reply_to.answer(result.post_text[1024:])
        except Exception:
            log.exception("Не удалось отправить фото, шлю только текст")
            await reply_to.answer(result.post_text)
    else:
        await reply_to.answer(result.post_text)

    template = messages.GENERATION_DONE_MOCK if settings.mock_linkedin else messages.GENERATION_DONE
    await reply_to.answer(
        template.format(
            post_id=result.linkedin_post_id or "",
            cost=result.cost_cents / 100,
            balance=result.new_balance / 100,
        ),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


# ── Settings ──────────────────────────────────────────────────────────────────

@router.message(Command("settings"))
@router.callback_query(F.data == "settings")
async def show_settings(event: Message | CallbackQuery) -> None:
    tg_id = event.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            return
        daily = user.daily_notifications
        ints = ", ".join(label(s) for s in user.interests) or "не выбраны"

    text = messages.SETTINGS_INFO.format(
        daily="✅ включены" if daily else "❌ выключены",
        interests=ints,
    )
    kb = keyboards.settings_keyboard(daily_enabled=daily)
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "toggle_daily")
@router.message(Command("notifications"))
async def toggle_daily(event: Message | CallbackQuery) -> None:
    tg_id = event.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            return
        user.daily_notifications = not user.daily_notifications
        new_state = user.daily_notifications

    text = f"🔔 Ежедневные напоминания: {'включены' if new_state else 'выключены'}"
    if isinstance(event, CallbackQuery):
        await event.answer(text)
    else:
        await event.answer(text)


@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery) -> None:
    await callback.answer()
    # callback.message.from_user — это бот, поэтому достаём профиль из БД по callback.from_user.id
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        authorized = user.is_authorized if user else False
        balance_cents = user.balance_cents if user else 0

    cost_cents = settings.cost_per_post_cents
    posts = balance_cents // cost_cents if cost_cents else 0
    await callback.message.answer(
        messages.WELCOME.format(
            name=callback.from_user.first_name or "друг",
            balance=f"{balance_cents/100:.2f}",
            cost=f"{cost_cents/100:.2f}",
            posts=posts,
        ),
        parse_mode="HTML",
        reply_markup=keyboards.main_menu(authorized=authorized),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено. /start чтобы вернуться в меню.")
