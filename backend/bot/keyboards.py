"""
Inline keyboards for the bot — all labels in English.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from backend.services.interests import INTERESTS


def main_menu(authorized: bool) -> InlineKeyboardMarkup:
    rows = []
    if not authorized:
        rows.append([InlineKeyboardButton(text="🔗 Connect LinkedIn", callback_data="oauth_start")])
    else:
        rows.append([InlineKeyboardButton(text="✨ Generate post", callback_data="generate")])
    rows.append([
        InlineKeyboardButton(text="🎯 Topics",  callback_data="interests"),
        InlineKeyboardButton(text="💰 Balance", callback_data="balance"),
    ])
    rows.append([InlineKeyboardButton(text="⚙️ Settings", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def interests_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    selected_set = set(selected)
    for slug, label in INTERESTS.items():
        check = "✅ " if slug in selected_set else "▫️ "
        rows.append([
            InlineKeyboardButton(text=f"{check}{label}", callback_data=f"int_toggle:{slug}")
        ])
    rows.append([InlineKeyboardButton(text="✔️ Done", callback_data="int_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="$5",  callback_data="topup:500"),
            InlineKeyboardButton(text="$10", callback_data="topup:1000"),
            InlineKeyboardButton(text="$25", callback_data="topup:2500"),
        ],
        [InlineKeyboardButton(text="« Back", callback_data="back_main")],
    ])


def balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Top up", callback_data="topup_menu")],
        [InlineKeyboardButton(text="« Back",    callback_data="back_main")],
    ])


def settings_keyboard(daily_enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔕 Disable reminders" if daily_enabled else "🔔 Enable reminders"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text,             callback_data="toggle_daily")],
        [InlineKeyboardButton(text="⏰ Change time",          callback_data="nt_change_time")],
        [InlineKeyboardButton(text="📅 Change days",          callback_data="nt_change_days")],
        [InlineKeyboardButton(text="🎯 Change topics",        callback_data="interests")],
        [InlineKeyboardButton(text="« Back",                  callback_data="back_main")],
    ])


# ── Notification time picker ────────────────────────────────────────────────

def hour_picker_keyboard() -> InlineKeyboardMarkup:
    """Сетка 24 часов, 6 рядов по 4 кнопки."""
    rows = []
    for start in range(0, 24, 4):
        row = [
            InlineKeyboardButton(text=f"{h:02d}", callback_data=f"nt_hour:{h}")
            for h in range(start, start + 4)
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton(text="« Back to settings", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def minute_picker_keyboard(hour: int) -> InlineKeyboardMarkup:
    """4 кнопки: :00, :15, :30, :45."""
    rows = [
        [
            InlineKeyboardButton(text=f"{hour:02d}:00", callback_data=f"nt_set:{hour}:0"),
            InlineKeyboardButton(text=f"{hour:02d}:15", callback_data=f"nt_set:{hour}:15"),
            InlineKeyboardButton(text=f"{hour:02d}:30", callback_data=f"nt_set:{hour}:30"),
            InlineKeyboardButton(text=f"{hour:02d}:45", callback_data=f"nt_set:{hour}:45"),
        ],
        [InlineKeyboardButton(text="« Choose another hour", callback_data="nt_change_time")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Notification days picker ────────────────────────────────────────────────

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def days_picker_keyboard(selected: list[int]) -> InlineKeyboardMarkup:
    """7 чекбокс-кнопок (Mon-Sun) + пресеты + Done."""
    sel = set(selected)
    rows = []
    # Дни — по 4 в ряд
    row = []
    for i, name in enumerate(_WEEKDAY_NAMES):
        check = "✅ " if i in sel else "▫️ "
        row.append(InlineKeyboardButton(text=f"{check}{name}", callback_data=f"nd_toggle:{i}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    # Пресеты
    rows.append([
        InlineKeyboardButton(text="📆 Every day",       callback_data="nd_preset:all"),
        InlineKeyboardButton(text="💼 Weekdays",         callback_data="nd_preset:weekdays"),
        InlineKeyboardButton(text="🏖 Weekends",         callback_data="nd_preset:weekends"),
    ])
    rows.append([InlineKeyboardButton(text="✔️ Save", callback_data="nd_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_days(days: list[int]) -> str:
    """Красиво форматирует список дней для отображения."""
    days = sorted(set(days))
    if not days:
        return "no days selected"
    if days == [0, 1, 2, 3, 4, 5, 6]:
        return "every day"
    if days == [0, 1, 2, 3, 4]:
        return "weekdays (Mon–Fri)"
    if days == [5, 6]:
        return "weekends (Sat–Sun)"
    return ", ".join(_WEEKDAY_NAMES[d] for d in days)


# ── Generate flow keyboards ──────────────────────────────────────────────────

def topic_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Pick from my interests", callback_data="gen_auto_topic")],
        [InlineKeyboardButton(text="❌ Cancel",                  callback_data="gen_cancel")],
    ])


def topic_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, let's go!",    callback_data="gen_confirm_topic")],
        [InlineKeyboardButton(text="🎲 Another topic",     callback_data="gen_another_topic")],
        [InlineKeyboardButton(text="✏️ I'll type my own",  callback_data="gen_manual_topic")],
    ])


def text_approval_keyboard(regen_cost_usd: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎨 Generate images",
            callback_data="gen_approve_text",
        )],
        [InlineKeyboardButton(
            text=f"🔄 Regenerate text (−${regen_cost_usd:.2f})",
            callback_data="gen_regen_text",
        )],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="gen_cancel")],
    ])


def final_approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Publish to LinkedIn",    callback_data="gen_publish")],
        [InlineKeyboardButton(text="❌ Cancel (don't publish)", callback_data="gen_cancel")],
    ])
