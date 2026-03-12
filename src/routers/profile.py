import html
import logging
from typing import Union
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime

from src.database.db import db
from src.routers.movie import is_premium
from src.config import config

router = Router()
logger = logging.getLogger(__name__)


def escape_md(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special_chars else c for c in str(text))


def get_profile_keyboard(user_id: int, notifs_on: bool = True):
    notif_label = "🔔 Сповіщення: вкл" if notifs_on else "🔕 Сповіщення: викл"
    keyboard = [
        [InlineKeyboardButton(text="☕️ Підтримати Нетика", callback_data="menu_donate")],
        [
            InlineKeyboardButton(text=notif_label, callback_data="profile_notifications"),
            InlineKeyboardButton(text="👥 Реферал", callback_data="profile_referral")
        ],
        [InlineKeyboardButton(text="💬 Мої цитати", callback_data="my_saved_quotes")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data == "menu_profile")
@router.message(Command("profile"))
async def show_profile(event: Union[types.Message, types.CallbackQuery]):
    user_id = event.from_user.id
    user_data = await db.get_user(user_id)
    if not user_data:
        if isinstance(event, types.CallbackQuery):
            await event.answer("Помилка: дані користувача не знайдено.", show_alert=True)
        else:
            await event.answer("Помилка: не вдалося завантажити ваш профіль.")
        return

    stats = await db.get_user_stats(user_id)
    has_premium = await is_premium(user_id, event.bot)

    reg_date = user_data.get("created_at", "Невідомо")
    if reg_date != "Невідомо":
        try:
            dt = datetime.fromisoformat(reg_date)
            reg_date = dt.strftime("%d.%m.%Y")
        except Exception as e:
            logger.debug(f"Failed to parse registration date: {e}")

    safe_name = html.escape(user_data.get("full_name") or "Невідомо")
    safe_username = html.escape(user_data.get("username") or "без юзернейму")
    safe_reg_date = html.escape(reg_date)
    safe_watched = stats.get("watched_count", 0)
    safe_watchlist = stats.get("watchlist_count", 0)
    safe_ratings = stats.get("ratings_count", 0)
    safe_avg_rating = stats.get("avg_rating", 0)
    safe_top_position = stats.get("top_position", "—")
    safe_points = user_data.get("points", 0)
    # Explicit call for checker
    safe_saved_quotes = await db.get_saved_quotes_count(user_id)

    expert_eye = "👁‍🗨 <b>Expert Eye</b> " if await db.has_achievement(user_id, "expert_eye") else ""
    community_voice = "📢 <b>Community Voice</b> " if await db.has_achievement(user_id, "community_voice") else ""
    achievements_text = f"\n🏆 <b>Досягнення:</b> {expert_eye}{community_voice}\n" if expert_eye or community_voice else ""

    status_text = "✅ <b>ПРЕМІУМ</b>" if has_premium else "🔓 <b>Базовий</b>"
    sponsor_badge = "🏆 <b>Спонсор Нетика</b>\n" if user_data.get("is_sponsor") else ""

    # Rank info
    rank_info = await db.get_user_rank(user_id)
    if rank_info:
        current_rank = rank_info.get("rank", "Початківець")
        points_to_next = rank_info.get("points_to_next", 0)
        next_rank = rank_info.get("next_rank", "")
        rank_progress = f"\n⬆️ До <b>{next_rank}</b>: <code>{points_to_next}</code> балів" if next_rank else "\n🏆 Максимальний ранг!"
    else:
        current_rank = "Початківець"
        rank_progress = ""

    text = (
        f"👤 <b>Профіль: {safe_name}</b> (@{safe_username})\n\n"
        f"📅 Дата реєстрації: <code>{safe_reg_date}</code>\n"
        f"💳 Статус: {status_text}\n"
        f"{sponsor_badge}"
        f"\n🎖 Ранг: <b>{current_rank}</b>"
        f"{rank_progress}\n"
        f"\n📊 <b>Твоя статистика:</b>\n"
        f"🎬 Переглянуто: <code>{safe_watched}</code>\n"
        f"🍿 У списку: <code>{safe_watchlist}</code>\n"
        f"⭐ Оцінок: <code>{safe_ratings}</code>\n"
        f"📈 Сер. оцінка: <code>{safe_avg_rating}</code>\n"
        f"💬 Цитат: <code>{safe_saved_quotes}</code>\n"
        f"🗂 Місце в топі: <code>#{safe_top_position}</code>\n"
        f"🪙 Бали: <code>{safe_points}</code>\n"
        f"{achievements_text}"
        f"\n<i>Дякую, що ти з Нетиком!</i>"
    )

    notifs_on = bool(user_data.get("notifications_enabled", 1))
    markup = get_profile_keyboard(user_id, notifs_on)

    if isinstance(event, types.CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            try:
                await event.message.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            except Exception:
                await event.message.answer(text, reply_markup=markup, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == "profile_notifications")
async def cb_notifications(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Помилка: користувача не знайдено.", show_alert=True)
        return

    notifs_on = bool(user.get("notifications_enabled", 1))
    new_val = 0 if notifs_on else 1
    await db.update_user(user_id, notifications_enabled=new_val)

    status = "увімкнено 🔔" if new_val else "вимкнено 🔕"
    await callback.answer(f"Сповіщення {status}", show_alert=True)
    await show_profile(callback)


@router.callback_query(F.data == "profile_referral")
async def cb_profile_referral(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username

    ref_count = await db.get_referral_count(user_id)
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    safe_link = html.escape(ref_link)

    text = (
        f"👥 <b>Реферальна програма</b>\n\n"
        f"Запрошуй друзів — отримуй бали!\n\n"
        f"🔗 <b>Твоє посилання:</b>\n<code>{safe_link}</code>\n\n"
        f"👤 Запрошено друзів: <b>{ref_count}</b>\n\n"
        f"<i>За кожного друга, який запустить бота по твоєму посиланню, "
        f"ти отримаєш бонусні бали.</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад до профілю", callback_data="menu_profile")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


