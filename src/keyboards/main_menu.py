"""
src/keyboards/main_menu.py
Клавіатури бота: онбординг + головне меню-акордеон.

Акордеон:
  - При відкриті бот показує 5 категорій-кнопок.
  - Натискання на категорію «розкриває» її — показує кнопки розділу.
  - Натискання на відкриту категорію — «закриває» (повертає до списку категорій).
  - Стан зберігається в callback_data: cat_open:<категорія>

Категорії:
  🔍 Пошук | 🎬 Моє кіно | 🎮 Розваги | 👤 Профіль | 💌 Зворотній зв'язок
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Set, Optional

from src.config import config

# ══════════════════════════════════════════════════════════════
#  Онбординг
# ══════════════════════════════════════════════════════════════

def get_onboarding_genres_kb(selected_genres: Set[str]) -> InlineKeyboardMarkup:
    genres = [
        ("Бойовик 👥", "Бойовик"), ("Комедія 😄", "Комедія"),
        ("Драма 🎭", "Драма"), ("Жахи 👻", "Жахи"),
        ("Фантастика 🚀", "Фантастика"), ("Мелодрама 🥰", "Мелодрама"),
        ("Анімація 🎨", "Анімація"), ("Документальна 🎙", "Документальна"),
    ]
    keyboard = []
    row = []
    for label, val in genres:
        marker = " ✅" if val in selected_genres else ""
        row.append(InlineKeyboardButton(text=f"{label}{marker}", callback_data=f"genre_{val}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    keyboard.append([InlineKeyboardButton(text="Готово ✅", callback_data="onboarding_genres_done")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_onboarding_frequency_kb() -> InlineKeyboardMarkup:
    options = [
        ("📅 Щодня", "daily"),
        ("🌿 Кілька разів на тиждень", "few_times_week"),
        ("🗓 Раз на тиждень", "once_week"),
        ("🌙 Зрідка", "rarely"),
    ]
    keyboard = [[InlineKeyboardButton(text=label, callback_data=f"freq_{val}")] for label, val in options]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_onboarding_period_kb() -> InlineKeyboardMarkup:
    options = [
        ("🎞 До 2000", "classic"),
        ("🎬 2000-ні", "2000s"),
        ("📱 2010-ні", "2010s"),
        ("🔥 2020+", "2020s"),
        ("🎲 Не важливо", "any"),
    ]
    keyboard = [[InlineKeyboardButton(text=label, callback_data=f"period_{val}")] for label, val in options]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ══════════════════════════════════════════════════════════════
#  Акордеон-меню
# ══════════════════════════════════════════════════════════════

# Категорії з emoji і ключами
CATEGORIES = [
    ("search",    "🔍 Пошук"),
    ("cinema",    "🎬 Моє кіно"),
    ("fun",       "🎮 Розваги"),
    ("profile",   "👤 Профіль"),
    ("feedback",  "💌 Зворотній зв'язок"),
]


def _get_category_buttons(key: str, is_subscribed: bool) -> list:
    """Повертає список рядків кнопок для розкритої категорії."""
    lock = " 🔒" if not is_subscribed else ""
    channel_url = f"https://t.me/{config.CHANNEL_USERNAME.replace('@', '')}"

    if key == "search":
        return [
            [InlineKeyboardButton(text="🔍 Знайти фільм",         callback_data="menu_search"),
             InlineKeyboardButton(text="🎃 Добірка дня",           callback_data="menu_daily_picks")],
            [InlineKeyboardButton(text=f"🤖 AI-рекомендація{lock}", callback_data="menu_ai_rec"),
             InlineKeyboardButton(text=f"🩶 По настрою{lock}",      callback_data="menu_mood")],
        ]
    elif key == "cinema":
        return [
            [InlineKeyboardButton(text="🌿 Мій список",            callback_data="menu_watchlist"),
             InlineKeyboardButton(text="⭐ Оцінки",                callback_data="menu_ratings")],
            [InlineKeyboardButton(text=f"📊 Статистика{lock}",     callback_data="menu_stats"),
             InlineKeyboardButton(text=f"🏆 Топ гравців{lock}",    callback_data="menu_leaderboard")],
            [InlineKeyboardButton(text="🎖 Топ фільмів спільноти",  callback_data="menu_top_movies")],
        ]
    elif key == "fun":
        return [
            [InlineKeyboardButton(text=f"🃏 Свайп-режим{lock}",    callback_data="menu_swipe"),
             InlineKeyboardButton(text=f"🎯 Вгадай рейтинг{lock}", callback_data="menu_guess")],
            [InlineKeyboardButton(text=f"👫 Разом{lock}",          callback_data="menu_together"),
             InlineKeyboardButton(text=f"🏅 Досягнення{lock}",     callback_data="menu_achievements")],
        ]
    elif key == "profile":
        return [
            [InlineKeyboardButton(text="👤 Мій профіль",           callback_data="menu_profile"),
             InlineKeyboardButton(text="🔔 Сповіщення",            callback_data="menu_notifications")],
            [InlineKeyboardButton(text="❓ Допомога",              callback_data="menu_help"),
             InlineKeyboardButton(text="📢 Наш канал",             url=channel_url)],
            [InlineKeyboardButton(text="💰 Донат",                 callback_data="menu_donate"),
             InlineKeyboardButton(text="🎁 Реферал",               callback_data="menu_referral")],
        ]
    elif key == "feedback":
        return [
            [InlineKeyboardButton(text="📬 Скринька пропозицій",   callback_data="menu_feedback")],
        ]
    return []


def get_main_menu_kb(is_subscribed: bool, open_cat: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Генерує клавіатуру акордеону.
    open_cat — ключ відкритої категорії (або None — всі закриті).
    """
    keyboard = []

    for key, label in CATEGORIES:
        is_open = (key == open_cat)
        # Кнопка категорії: якщо відкрита — показуємо ▼, якщо закрита — ▶
        arrow = "▼" if is_open else "▶"
        keyboard.append([InlineKeyboardButton(
            text=f"{arrow} {label}",
            callback_data=f"cat_close" if is_open else f"cat_open:{key}",
        )])

        # Якщо ця категорія відкрита — вставляємо її кнопки
        if is_open:
            buttons = _get_category_buttons(key, is_subscribed)
            keyboard.extend(buttons)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)