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
        [InlineKeyboardButton(text=toggle_text,         callback_data="toggle_daily")],
        [InlineKeyboardButton(text="🎯 Change topics",   callback_data="interests")],
        [InlineKeyboardButton(text="« Back",             callback_data="back_main")],
    ])


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
