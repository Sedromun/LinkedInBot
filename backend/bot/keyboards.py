"""
Inline-клавиатуры для бота.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from backend.services.interests import INTERESTS


def main_menu(authorized: bool) -> InlineKeyboardMarkup:
    """Главное меню. Меняется в зависимости от того, привязан ли LinkedIn."""
    rows = []
    if not authorized:
        rows.append([InlineKeyboardButton(text="🔗 Привязать LinkedIn", callback_data="oauth_start")])
    else:
        rows.append([InlineKeyboardButton(text="✨ Сгенерить пост", callback_data="generate")])
    rows.append([
        InlineKeyboardButton(text="🎯 Интересы",   callback_data="interests"),
        InlineKeyboardButton(text="💰 Баланс",     callback_data="balance"),
    ])
    rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def interests_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    """Чекбокс-клавиатура выбора интересов."""
    rows = []
    selected_set = set(selected)
    for slug, label in INTERESTS.items():
        check = "✅ " if slug in selected_set else "▫️ "
        rows.append([
            InlineKeyboardButton(text=f"{check}{label}", callback_data=f"int_toggle:{slug}")
        ])
    rows.append([InlineKeyboardButton(text="✔️ Готово", callback_data="int_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_keyboard() -> InlineKeyboardMarkup:
    """Готовые суммы для mock-пополнения."""
    rows = [
        [
            InlineKeyboardButton(text="$5",  callback_data="topup:500"),
            InlineKeyboardButton(text="$10", callback_data="topup:1000"),
            InlineKeyboardButton(text="$25", callback_data="topup:2500"),
        ],
        [InlineKeyboardButton(text="« Назад", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Пополнить", callback_data="topup_menu")],
        [InlineKeyboardButton(text="« Назад", callback_data="back_main")],
    ])


def generate_topic_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Подобрать из интересов", callback_data="gen_auto_topic")],
        [InlineKeyboardButton(text="« Отмена", callback_data="back_main")],
    ])


def settings_keyboard(daily_enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔕 Выключить напоминания" if daily_enabled else "🔔 Включить напоминания"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="toggle_daily")],
        [InlineKeyboardButton(text="🎯 Поменять интересы", callback_data="interests")],
        [InlineKeyboardButton(text="« Назад", callback_data="back_main")],
    ])
