"""
handlers.py — все команды и callback-кнопки.

Generate FSM:
  waiting_for_topic        → юзер вводит тему вручную
  confirming_auto_topic    → юзер подтверждает / меняет предложенную тему
  reviewing_text           → юзер смотрит сгенерированный текст, одобряет или перегенерирует
  reviewing_full_post      → юзер смотрит финальный пост с картинками, решает публиковать
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

from backend.bot import keyboards, messages
from backend.config import settings
from backend.db import crud
from backend.db.session import session_scope
from backend.logger import get_logger
from backend.services import billing_service, posting_service
from backend.services.billing_service import InsufficientFunds
from backend.services.interests import label

log = get_logger(__name__)
router = Router()


def _friendly_error(exc: Exception) -> str:
    """
    Converts a raw exception into a short, user-friendly message.
    Full error is always logged separately.
    """
    msg = str(exc).lower()

    if any(k in msg for k in ("503", "unavailable", "overload", "high demand",
                               "try again later", "temporarily", "capacity")):
        return "All AI models are temporarily overloaded. Please try again in a few minutes."

    if any(k in msg for k in ("429", "rate limit", "quota", "too many requests")):
        return "Rate limit reached. Please wait a moment and try again."

    if any(k in msg for k in ("401", "403", "invalid api key", "authentication",
                               "unauthorized", "permission")):
        return "API authentication error. Please contact support."

    if any(k in msg for k in ("network", "connection", "timeout", "timed out",
                               "connect error", "ssl")):
        return "Network error. Please try again."

    if "insufficient funds" in msg or "balance" in msg:
        return "Insufficient funds. Go to /balance to top up."

    if "linkedin" in msg and any(k in msg for k in ("not found", "invalid", "expired")):
        return "LinkedIn token has expired. Please reconnect via /start."

    return "Something went wrong during generation. Please try again."


# ── FSM состояния ────────────────────────────────────────────────────────────

class GenerateStates(StatesGroup):
    waiting_for_topic     = State()   # юзер набирает тему вручную
    confirming_auto_topic = State()   # подтверждение предложенной темы
    reviewing_text        = State()   # одобрение текста перед генерацией картинок
    reviewing_full_post   = State()   # финальный апрув перед публикацией


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
        authorized   = user.is_authorized
        balance_cents = user.balance_cents

    if created:
        log.info("New user | tg_id=%s username=%s", tg_user.id, tg_user.username)

    cost_cents = settings.cost_per_post_cents
    balance_usd = balance_cents / 100
    posts = int(balance_usd / (cost_cents / 100)) if cost_cents else 0

    if authorized:
        text = messages.WELCOME_AUTHORIZED.format(
            name=tg_user.first_name or "there",
            balance=balance_usd,
            posts=posts,
        )
    else:
        text = messages.WELCOME_NEW.format(
            name=tg_user.first_name or "there",
            balance=balance_usd,
            cost=cost_cents / 100,
            posts=posts,
        )

    await message.answer(text, parse_mode="HTML",
                         reply_markup=keyboards.main_menu(authorized=authorized))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Commands:\n"
        "/start — main menu\n"
        "/generate — create a post\n"
        "/interests — choose topics\n"
        "/balance — balance & top up\n"
        "/settings — settings\n"
        "/notifications — toggle daily reminders\n"
        "/cancel — cancel current action",
    )


# ── OAuth flow ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "oauth_start")
async def cb_oauth_start(callback: CallbackQuery) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            await callback.message.answer("Please send /start first.")
            return
        if user.is_authorized:
            await callback.message.answer(messages.OAUTH_ALREADY_DONE)
            return

    from backend.services import oauth_service
    if settings.mock_linkedin:
        await oauth_service.mock_authorize(tg_id)
        await callback.message.answer(messages.OAUTH_SUCCESS_MOCK, parse_mode="HTML")
    else:
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

    kb = keyboards.interests_keyboard(selected)
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(messages.CHOOSE_INTERESTS, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(messages.CHOOSE_INTERESTS, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("int_toggle:"))
async def cb_interest_toggle(callback: CallbackQuery) -> None:
    slug = callback.data.split(":", 1)[1]
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Please send /start first.", show_alert=True)
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
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.interests_keyboard(new_selected)
        )
    except Exception:
        pass


@router.callback_query(F.data == "int_done")
async def cb_interest_done(callback: CallbackQuery) -> None:
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        interests = user.interests if user else []

    if not interests:
        await callback.answer(messages.INTERESTS_EMPTY, show_alert=True)
        return

    labels = ", ".join(label(s) for s in interests)
    await callback.answer()
    await callback.message.answer(
        messages.INTERESTS_SAVED.format(labels=labels), parse_mode="HTML"
    )


# ── Balance / Topup ──────────────────────────────────────────────────────────

@router.message(Command("balance"))
@router.callback_query(F.data == "balance")
async def show_balance(event: Message | CallbackQuery) -> None:
    tg_id = event.from_user.id
    balance_cents = await billing_service.get_balance(tg_id)
    cost_cents  = settings.cost_per_post_cents
    regen_cents = settings.regen_text_cents
    posts = balance_cents // cost_cents if cost_cents else 0
    text = messages.BALANCE_INFO.format(
        balance=balance_cents / 100,
        cost=cost_cents / 100,
        regen=regen_cents / 100,
        posts=posts,
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, parse_mode="HTML", reply_markup=keyboards.balance_keyboard())
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=keyboards.balance_keyboard())


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


# ── Generate flow — запуск ────────────────────────────────────────────────────

@router.message(Command("generate"))
@router.callback_query(F.data == "generate")
async def cmd_generate(event: Message | CallbackQuery, state: FSMContext) -> None:
    tg_id = event.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user or not user.is_authorized:
            msg = messages.NOT_AUTHORIZED
            if isinstance(event, CallbackQuery):
                await event.answer()
                await event.message.answer(msg)
            else:
                await event.answer(msg)
            return

    await state.set_state(GenerateStates.waiting_for_topic)
    kb = keyboards.topic_start_keyboard()
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(messages.GENERATE_PROMPT, reply_markup=kb, parse_mode="HTML")
    else:
        await event.answer(messages.GENERATE_PROMPT, reply_markup=kb, parse_mode="HTML")


# ── Generate flow — автоматическая тема ─────────────────────────────────────

@router.callback_query(F.data == "gen_auto_topic")
async def cb_gen_auto_topic(callback: CallbackQuery, state: FSMContext) -> None:
    """Предложить рандомную тему из интересов, дождаться подтверждения."""
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user or not user.interests:
            await callback.answer(
                "First choose your topics: /interests", show_alert=True
            )
            return
        topic = await posting_service.suggest_topic_for_user(user)

    await state.set_state(GenerateStates.confirming_auto_topic)
    await state.update_data(suggested_topic=topic)
    await callback.answer()
    await callback.message.answer(
        messages.TOPIC_SUGGESTION.format(topic=topic),
        parse_mode="HTML",
        reply_markup=keyboards.topic_confirm_keyboard(),
    )


@router.callback_query(F.data == "gen_another_topic")
async def cb_gen_another_topic(callback: CallbackQuery, state: FSMContext) -> None:
    """Предложить другую тему (in-place замена сообщения)."""
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        if not user:
            await callback.answer("Please send /start first.", show_alert=True)
            return
        topic = await posting_service.suggest_topic_for_user(user)

    await state.update_data(suggested_topic=topic)
    await callback.answer()
    try:
        await callback.message.edit_text(
            messages.TOPIC_SUGGESTION.format(topic=topic),
            parse_mode="HTML",
            reply_markup=keyboards.topic_confirm_keyboard(),
        )
    except Exception:
        await callback.message.answer(
            messages.TOPIC_SUGGESTION.format(topic=topic),
            parse_mode="HTML",
            reply_markup=keyboards.topic_confirm_keyboard(),
        )


@router.callback_query(F.data == "gen_confirm_topic")
async def cb_gen_confirm_topic(callback: CallbackQuery, state: FSMContext) -> None:
    """Юзер подтвердил предложенную тему — запускаем генерацию текста."""
    data = await state.get_data()
    topic = data.get("suggested_topic", "")
    if not topic:
        await callback.answer("Something went wrong, please try /generate again.", show_alert=True)
        await state.clear()
        return

    await callback.answer()
    await state.clear()
    await _phase1_generate_text(callback.message, callback.from_user.id, topic, state)


@router.callback_query(F.data == "gen_manual_topic")
async def cb_gen_manual_topic(callback: CallbackQuery, state: FSMContext) -> None:
    """Юзер хочет ввести тему сам."""
    await callback.answer()
    await state.set_state(GenerateStates.waiting_for_topic)
    await callback.message.answer(messages.GENERATE_PROMPT, parse_mode="HTML",
                                   reply_markup=keyboards.topic_start_keyboard())


@router.message(GenerateStates.waiting_for_topic)
async def on_topic_received(message: Message, state: FSMContext) -> None:
    """Юзер ввёл тему вручную."""
    topic = (message.text or "").strip()
    if len(topic) < 3:
        await message.answer("Topic is too short. Try again or /cancel.")
        return
    await state.clear()
    await _phase1_generate_text(message, message.from_user.id, topic, state)


# ── Phase 1: генерация текста ─────────────────────────────────────────────────

async def _phase1_generate_text(
    reply_to: Message,
    tg_id: int,
    topic: str,
    state: FSMContext,
) -> None:
    """Запускает Phase 1, показывает текст и кнопки апрува."""
    progress = await reply_to.answer(
        messages.GENERATING_TEXT.format(topic=topic), parse_mode="HTML"
    )

    try:
        content = await posting_service.generate_text(topic)
    except Exception as e:
        log.exception("Phase 1 failed | user=%s topic=%r", tg_id, topic)
        await reply_to.answer(
            messages.GENERATION_FAILED.format(error=_friendly_error(e)), parse_mode="HTML"
        )
        return

    post_text     = content["post"]
    image_prompts = content.get("image_prompts", [])

    await state.set_state(GenerateStates.reviewing_text)
    await state.update_data(topic=topic, post_text=post_text, image_prompts=image_prompts)

    regen_usd = settings.regen_text_cents / 100

    # Шлём текст + кнопки
    await reply_to.answer(messages.TEXT_PREVIEW_HEADER, parse_mode="HTML")
    await reply_to.answer(post_text)
    await reply_to.answer(
        messages.TEXT_PREVIEW_FOOTER.format(chars=len(post_text), regen=regen_usd),
        parse_mode="HTML",
        reply_markup=keyboards.text_approval_keyboard(regen_usd),
    )


# ── Апрув / перегенерация текста ─────────────────────────────────────────────

@router.callback_query(F.data == "gen_approve_text")
async def cb_approve_text(callback: CallbackQuery, state: FSMContext) -> None:
    """Юзер доволен текстом — идём генерировать картинки (Phase 2)."""
    data = await state.get_data()
    topic         = data.get("topic", "")
    post_text     = data.get("post_text", "")
    image_prompts = data.get("image_prompts", [])

    await callback.answer()
    await state.set_state(GenerateStates.reviewing_full_post)

    count = len(image_prompts)
    if count == 0:
        # Нет промптов — сразу к финальному апруву без картинок
        await state.update_data(image_paths=[])
        await _show_final_preview(callback.message, callback.from_user.id, state)
        return

    noun = "image" if count == 1 else "images"
    await callback.message.answer(
        messages.GENERATING_IMAGES.format(count=count, noun=noun),
        parse_mode="HTML",
    )

    try:
        image_paths = await posting_service.generate_images(image_prompts)
    except Exception as e:
        log.warning("Phase 2 failed (продолжаем без картинок) | user=%s: %s",
                    callback.from_user.id, e)
        image_paths = []

    await state.update_data(image_paths=image_paths)
    await _show_final_preview(callback.message, callback.from_user.id, state)


@router.callback_query(F.data == "gen_regen_text")
async def cb_regen_text(callback: CallbackQuery, state: FSMContext) -> None:
    """Юзер хочет перегенерировать текст за $0.50."""
    tg_id = callback.from_user.id
    data  = await state.get_data()
    topic = data.get("topic", "")

    try:
        new_balance = await posting_service.charge_for_regen(tg_id)
    except InsufficientFunds as e:
        balance = await billing_service.get_balance(tg_id)
        await callback.answer(
            f"Insufficient funds (need ${settings.regen_text_cents/100:.2f},"
            f" have ${balance/100:.2f})",
            show_alert=True,
        )
        return

    await callback.answer()
    await callback.message.answer(
        messages.REGEN_CHARGED.format(regen=settings.regen_text_cents / 100),
        parse_mode="HTML",
    )

    await state.set_state(GenerateStates.reviewing_text)  # сбрасываем состояние
    await _phase1_generate_text(callback.message, tg_id, topic, state)


# ── Финальный предпросмотр ────────────────────────────────────────────────────

async def _show_final_preview(
    reply_to: Message,
    tg_id: int,
    state: FSMContext,
) -> None:
    """Отправляет картинки + текст + кнопки финального апрува."""
    data        = await state.get_data()
    post_text   = data.get("post_text", "")
    image_paths = data.get("image_paths", [])
    cost_cents  = settings.cost_per_post_cents
    balance     = await billing_service.get_balance(tg_id)

    await reply_to.answer(messages.FINAL_PREVIEW_HEADER, parse_mode="HTML")

    # Шлём картинки
    await _send_images_only(reply_to, image_paths)

    # Шлём текст
    await reply_to.answer(post_text)

    # Кнопки
    await reply_to.answer(
        messages.FINAL_PREVIEW_FOOTER.format(
            cost=cost_cents / 100,
            balance=balance / 100,
        ),
        parse_mode="HTML",
        reply_markup=keyboards.final_approval_keyboard(),
    )


# ── Публикация ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "gen_publish")
async def cb_publish(callback: CallbackQuery, state: FSMContext) -> None:
    """Юзер нажал «Опубликовать» — Phase 3."""
    tg_id = callback.from_user.id
    data  = await state.get_data()

    topic         = data.get("topic", "")
    post_text     = data.get("post_text", "")
    image_prompts = data.get("image_prompts", [])
    image_paths   = data.get("image_paths", [])

    await callback.answer()
    await state.clear()

    try:
        post_id, new_balance = await posting_service.publish(
            tg_id=tg_id,
            topic=topic,
            post_text=post_text,
            image_prompts=image_prompts,
            image_paths=image_paths,
        )
    except InsufficientFunds as e:
        balance = await billing_service.get_balance(tg_id)
        await callback.message.answer(
            messages.INSUFFICIENT_FUNDS.format(
                need=settings.cost_per_post_cents / 100,
                balance=balance / 100,
            ),
            parse_mode="HTML",
        )
        return
    except Exception as e:
        log.exception("Phase 3 (publish) failed | user=%s", tg_id)
        await callback.message.answer(
            messages.GENERATION_FAILED.format(error=_friendly_error(e)), parse_mode="HTML"
        )
        return

    template = messages.PUBLISHED_MOCK if settings.mock_linkedin else messages.PUBLISHED
    await callback.message.answer(
        template.format(
            post_id=post_id or "",
            cost=settings.cost_per_post_cents / 100,
            balance=new_balance / 100,
        ),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


@router.callback_query(F.data == "gen_cancel")
@router.message(Command("cancel"))
async def cmd_cancel(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    msg = messages.PUBLISH_CANCELLED
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(msg, parse_mode="HTML")
    else:
        await event.answer(msg, parse_mode="HTML")


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
        ints  = ", ".join(label(s) for s in user.interests) or "not set"
        time_ = user.notification_time
        days_ = keyboards.format_days(user.notification_days)

    text = messages.SETTINGS_INFO.format(
        daily="✅ enabled" if daily else "❌ disabled",
        time=time_,
        days=days_,
        interests=ints,
    )
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(text, reply_markup=keyboards.settings_keyboard(daily),
                                   parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=keyboards.settings_keyboard(daily), parse_mode="HTML")


@router.callback_query(F.data == "toggle_daily")
@router.message(Command("notifications"))
async def toggle_daily(event: Message | CallbackQuery) -> None:
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, event.from_user.id)
        if not user:
            return
        user.daily_notifications = not user.daily_notifications
        new_state = user.daily_notifications

    text = f"🔔 Daily reminders: {'enabled' if new_state else 'disabled'}"
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    else:
        await event.answer(text)


# ── Notification time picker ──────────────────────────────────────────────────

@router.callback_query(F.data == "nt_change_time")
async def cb_nt_change_time(callback: CallbackQuery) -> None:
    """Шаг 1: показать сетку часов."""
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        current = user.notification_time if user else "18:00"

    await callback.answer()
    await callback.message.answer(
        messages.PICK_HOUR.format(current=current),
        parse_mode="HTML",
        reply_markup=keyboards.hour_picker_keyboard(),
    )


@router.callback_query(F.data.startswith("nt_hour:"))
async def cb_nt_hour(callback: CallbackQuery) -> None:
    """Шаг 2: юзер выбрал час → показываем минуты."""
    hour = int(callback.data.split(":", 1)[1])
    await callback.answer()
    await callback.message.answer(
        messages.PICK_MINUTE.format(hour=hour),
        parse_mode="HTML",
        reply_markup=keyboards.minute_picker_keyboard(hour),
    )


@router.callback_query(F.data.startswith("nt_set:"))
async def cb_nt_set(callback: CallbackQuery) -> None:
    """Шаг 3: юзер выбрал минуты → сохраняем в БД."""
    _, hour_str, minute_str = callback.data.split(":")
    hour, minute = int(hour_str), int(minute_str)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        await callback.answer("Bad time", show_alert=True)
        return

    time_str = f"{hour:02d}:{minute:02d}"
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Send /start first", show_alert=True)
            return
        user.notification_time = time_str

    log.info("User %s set notification_time=%s", callback.from_user.id, time_str)
    await callback.answer()
    await callback.message.answer(
        messages.TIME_SAVED.format(time=time_str), parse_mode="HTML"
    )


# ── Notification days picker ──────────────────────────────────────────────────

@router.callback_query(F.data == "nt_change_days")
async def cb_nt_change_days(callback: CallbackQuery, state: FSMContext) -> None:
    """Показываем чекбокс-клавиатуру дней. Текущий набор — из БД."""
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Send /start first", show_alert=True)
            return
        current_days = list(user.notification_days)

    # Храним выбранные дни в FSM, чтобы не дёргать БД на каждый toggle
    await state.update_data(picking_days=current_days)
    await callback.answer()
    await callback.message.answer(
        messages.PICK_DAYS.format(current=keyboards.format_days(current_days)),
        parse_mode="HTML",
        reply_markup=keyboards.days_picker_keyboard(current_days),
    )


@router.callback_query(F.data.startswith("nd_toggle:"))
async def cb_nd_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    """Тогл одного дня (Mon/Tue/.../Sun) в FSM-буфере."""
    day = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    days = list(data.get("picking_days", []))
    if day in days:
        days.remove(day)
    else:
        days.append(day)
    days = sorted(set(days))
    await state.update_data(picking_days=days)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.days_picker_keyboard(days)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("nd_preset:"))
async def cb_nd_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """Пресеты: every day / weekdays / weekends."""
    preset = callback.data.split(":", 1)[1]
    if preset == "all":
        days = [0, 1, 2, 3, 4, 5, 6]
    elif preset == "weekdays":
        days = [0, 1, 2, 3, 4]
    elif preset == "weekends":
        days = [5, 6]
    else:
        await callback.answer("Unknown preset", show_alert=True)
        return

    await state.update_data(picking_days=days)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.days_picker_keyboard(days)
        )
    except Exception:
        pass


@router.callback_query(F.data == "nd_done")
async def cb_nd_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохранить выбранные дни в БД."""
    data = await state.get_data()
    days = sorted(set(data.get("picking_days", [])))

    if not days:
        await callback.answer(messages.DAYS_EMPTY, show_alert=True)
        return

    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, callback.from_user.id)
        if not user:
            await callback.answer("Send /start first", show_alert=True)
            return
        user.notification_days = days

    await state.update_data(picking_days=None)
    log.info("User %s set notification_days=%s", callback.from_user.id, days)

    pretty = keyboards.format_days(days)
    await callback.answer()
    await callback.message.answer(
        messages.DAYS_SAVED.format(days=pretty), parse_mode="HTML"
    )


@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery) -> None:
    await callback.answer()
    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await crud.get_user_by_tg(session, tg_id)
        authorized    = user.is_authorized if user else False
        balance_cents = user.balance_cents if user else 0

    cost_cents = settings.cost_per_post_cents
    posts = balance_cents // cost_cents if cost_cents else 0

    if authorized:
        text = messages.WELCOME_AUTHORIZED.format(
            name=callback.from_user.first_name or "there",
            balance=balance_cents / 100,
            posts=posts,
        )
    else:
        text = messages.WELCOME_NEW.format(
            name=callback.from_user.first_name or "there",
            balance=balance_cents / 100,
            cost=cost_cents / 100,
            posts=posts,
        )
    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=keyboards.main_menu(authorized=authorized),
    )


# ── Вспомогалки ──────────────────────────────────────────────────────────────

async def _send_images_only(reply_to: Message, image_paths: list[str]) -> None:
    """Шлёт картинки без текста (для финального предпросмотра)."""
    if not image_paths:
        return
    if len(image_paths) == 1:
        try:
            await reply_to.answer_photo(FSInputFile(image_paths[0]))
        except Exception:
            log.exception("Не удалось отправить фото")
    else:
        try:
            media = [InputMediaPhoto(media=FSInputFile(p)) for p in image_paths[:10]]
            await reply_to.answer_media_group(media)
        except Exception:
            log.exception("Не удалось отправить media_group")
