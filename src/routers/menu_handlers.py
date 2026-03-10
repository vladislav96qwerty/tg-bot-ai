"""
src/routers/menu_handlers.py
Обробники головного меню з акордеоном.

ВИПРАВЛЕНО: узгоджено callback_data з чекером v5, стандартизовано parse_mode="HTML".
"""
import json
import html
import logging
import asyncio

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

from src.database.db import db
from src.routers.movie import is_premium
from src.services.tmdb import tmdb_service
from src.services.ai import ai_service
from src.services.prompts import MOOD_RECOMMENDATION_PROMPT
from src.keyboards.main_menu import get_main_menu_kb
from src.config import config

router = Router()
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  FSM — Скринька зворотного зв'язку
# ══════════════════════════════════════════════════════════════

class FeedbackStates(StatesGroup):
    CHOOSING_TYPE = State()
    WRITING_TEXT  = State()


# ══════════════════════════════════════════════════════════════
#  Акордеон — відкрити / закрити категорію
# ══════════════════════════════════════════════════════════════

async def _edit_menu(callback: types.CallbackQuery, open_cat: str | None = None):
    """Редагує поточне повідомлення — показує меню з відкритою/закритою категорією."""
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)
    markup = get_main_menu_kb(has_premium, open_cat=open_cat)
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except Exception:
        safe_name = html.escape(callback.from_user.first_name)
        try:
            await callback.message.edit_text(
                f"Привіт, {safe_name}! 👋\nЯ — <b>Нетик</b>, твій кіногід 🎬\nЩо шукаємо сьогодні?",
                reply_markup=markup,
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.answer(
                f"Привіт, {safe_name}! 👋\nЯ — <b>Нетик</b>, твій кіногід 🎬\nЩо шукаємо сьогодні?",
                reply_markup=markup,
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("cat_open:"))
async def cb_cat_open(callback: types.CallbackQuery):
    """Розкриває обрану категорію."""
    if not callback.message:
        await callback.answer()
        return
    key = callback.data.split(":")[1]
    await _edit_menu(callback, open_cat=key)
    await callback.answer()


@router.callback_query(F.data == "cat_close")
async def cb_cat_close(callback: types.CallbackQuery):
    """Закриває поточну категорію."""
    if not callback.message:
        await callback.answer()
        return
    await _edit_menu(callback, open_cat=None)
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  1. SEARCH
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_search")
async def cb_menu_search(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    text = (
        "🔍 <b>Пошук фільму</b>\n\n"
        "Просто напиши назву фільму текстом — "
        "і Нетик знайде його для тебе!"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  2. MOOD
# ══════════════════════════════════════════════════════════════

MOOD_OPTIONS = [
    ("🥺 Сумно", "sad"),
    ("🤬 Злий", "angry"),
    ("🥰 Романтично", "romantic"),
    ("🱋 Адреналін", "adrenaline"),
    ("😄 Весело", "funny"),
    ("🤔 Задуматись", "thoughtful"),
]

MOOD_LABELS = {
    "sad": "🥺 Сумно",
    "angry": "🤬 Злий",
    "romantic": "🥰 Романтично",
    "adrenaline": "🱋 Адреналін",
    "funny": "😄 Весело",
    "thoughtful": "🤔 Задуматись",
}


@router.callback_query(F.data == "menu_mood")
async def cb_menu_mood(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)

    if not has_premium:
        return await callback.answer(
            "🔒 Фільтр за настроєм доступний підписникам каналу!",
            show_alert=True,
        )

    text = (
        "🧠 <b>Який у тебе настрій зараз?</b>\n\n"
        "Обери — і Нетик підбере ідеальне кіно під нього."
    )
    keyboard = []
    row = []
    for label, key in MOOD_OPTIONS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"mood_pick:{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")])

    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mood_pick:"))
async def cb_mood_pick(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    mood_key = callback.data.split(":")[1]
    mood_label = MOOD_LABELS.get(mood_key, mood_key)
    user_id = callback.from_user.id

    await callback.answer()
    try:
        await callback.message.edit_text(
            f"🎬 <b>Нетик підбирає кіно під настрій {mood_label}...</b>\n"
            "Зачекай трішки ⏳",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"Mood pick edit failed: {e}")

    try:
        popular = await tmdb_service.get_popular(page=1)
        movies_for_ai = [
            {
                "id": m.get("id"),
                "title": m.get("title"),
                "year": (m.get("release_date") or "")[:4],
                "overview": (m.get("overview") or "")[:100],
            }
            for m in popular[:15]
        ]

        watched = await db.get_watched_titles(user_id)

        prompt = MOOD_RECOMMENDATION_PROMPT.format(
            mood=mood_label,
            tmdb_movies_json=json.dumps(movies_for_ai, ensure_ascii=False),
            watched_titles=", ".join(watched[:20]) if watched else "Ще нічого",
        )

        res = await ai_service.ask(prompt, expect_json=True)
        if not res or "films" not in res:
            try:
                await callback.message.edit_text(
                    "🔎 Нетик не зміг підібрати фільми. Спробуй пізніше!",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
                    ]),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Помилка відображення повідомлення про відсутність фільмів: {e}")
            return

        text = f"🧠 <b>Настрій: {mood_label}</b>\n\n"
        if res.get("mood_response"):
            text += f"<i>{html.escape(res['mood_response'])}</i>\n\n"

        keyboard = []
        for film in res.get("films", [])[:5]:
            tmdb_id = film.get("tmdb_id")
            title = film.get("title_ua", "Фільм")
            mood_match = film.get("mood_match", "")
            promise = film.get("promise", "")

            text += f"🎬 <b>{html.escape(title)}</b>\n"
            if mood_match:
                text += f"   {html.escape(mood_match)}\n"
            if promise:
                text += f"   ✨ <i>{html.escape(promise)}</i>\n"
            text += "\n"

            if tmdb_id:
                keyboard.append([InlineKeyboardButton(
                    text=f"🎬 {title}",
                    callback_data=f"movie_id:{tmdb_id}",
                )])

        keyboard.append([InlineKeyboardButton(text="🔄 Інший настрій", callback_data="menu_mood")])
        keyboard.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")])

        try:
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.error(f"Mood recommendation error: {e}", exc_info=True)
        try:
            await callback.message.edit_text(
                "🔎 Щось пішло не так. Спробуй ще раз!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
                ]),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Помилка відображення меню: {e}")


# ══════════════════════════════════════════════════════════════
#  3. RATINGS
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_ratings")
async def cb_menu_ratings(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    ratings = await db.get_user_ratings_list(user_id)

    text = f"⭐ <b>Мої оцінки</b> ({len(ratings)})\n\n"
    if not ratings:
        text += "<i>Ти ще не оцінив жодного фільму.\nЗнайди фільм через пошук і постав оцінку!</i>"
    else:
        for i, r in enumerate(ratings[:15], 1):
            text += f"{i}. {html.escape(r['title_ua'])} — ⭐ {r['rating']}/10\n"
        if len(ratings) > 15:
            text += f"\n<i>...та ще {len(ratings) - 15} оцінок</i>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  4. STATS
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_stats")
async def cb_menu_stats(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)

    if not has_premium:
        return await callback.answer(
            "🔒 Статистика доступна підписникам каналу!", show_alert=True
        )

    stats = await db.get_user_stats(user_id)
    if not stats:
        await callback.answer("Статистика недоступна.")
        return

    text = (
        "📊 <b>Твоя статистика</b>\n\n"
        f"🎬 Переглянуто: <b>{stats['watched_count']}</b>\n"
        f"🍿 У списку: <b>{stats['watchlist_count']}</b>\n"
        f"⭐ Оцінок: <b>{stats['ratings_count']}</b>\n"
        f"📐 Середня оцінка: <b>{stats['avg_rating']}</b>/10\n"
        f"🏆 Місце в топі: <b>#{stats['top_position']}</b>\n"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ гравців", callback_data="menu_leaderboard")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  5. LEADERBOARD
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_leaderboard")
async def cb_menu_leaderboard(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)

    if not has_premium:
        return await callback.answer(
            "🔒 Лідерборд доступний підписникам каналу!", show_alert=True
        )

    players = await db.get_top_players(limit=10)

    text = "🏆 <b>Топ-10 гравців Нетика</b>\n\n"
    if not players:
        text += "<i>Поки що тут порожньо. Будь першим!</i>"
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, p in enumerate(players, 1):
            medal = medals.get(i, f"{i}.")
            name = html.escape(p.get("full_name") or p.get("username") or "Анонім")
            points = p.get("points", 0)
            you = " ← ти" if p["user_id"] == user_id else ""
            text += f"{medal} <b>{name}</b> — {points} балів{you}\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="menu_stats")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  6. ACHIEVEMENTS
# ══════════════════════════════════════════════════════════════

ACHIEVEMENT_INFO = {
    "expert_eye":       ("🎯 Експертне око",     "Вгадав рейтинг з точністю ±0.5"),
    "community_voice":  ("📢 Голос спільноти",   "Проголосував у 5+ опитуваннях"),
}


@router.callback_query(F.data == "menu_achievements")
async def cb_menu_achievements(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)

    if not has_premium:
        return await callback.answer(
            "🔒 Досягнення доступні підписникам каналу!", show_alert=True
        )

    text = "🏅 <b>Мої досягнення</b>\n\n"
    earned_count = 0

    for key, (title, desc) in ACHIEVEMENT_INFO.items():
        has = await db.has_achievement(user_id, key)
        if has:
            text += f"✅ <b>{title}</b>\n   <i>{desc}</i>\n\n"
            earned_count += 1
        else:
            text += f"🔒 {title}\n   <i>{desc}</i>\n\n"

    text += f"Отримано: <b>{earned_count}/{len(ACHIEVEMENT_INFO)}</b>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  7. NOTIFICATIONS
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_notifications")
async def cb_menu_notifications(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Користувача не знайдено.")
        return
    notifs_on = bool(user.get("notifications_enabled", 1))

    new_val = 0 if notifs_on else 1
    await db.update_user(user_id, notifications_enabled=new_val)

    if new_val:
        text = "🔔 <b>Сповіщення увімкнено!</b>\n\nНетик повідомлятиме тебе про нові добірки та рекомендації."
    else:
        text = "🔕 <b>Сповіщення вимкнено.</b>\n\nТи більше не отримуватимеш повідомлень від Нетика."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Змінити", callback_data="menu_notifications")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer(f"{'Увімкнено 🔔' if new_val else 'Вимкнено 🔕'}")


# ══════════════════════════════════════════════════════════════
#  8. HELP
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_help")
async def cb_menu_help(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    channel = config.CHANNEL_USERNAME.replace("@", "")
    text = (
        "❓ <b>Допомога — НеНетфліксБот</b>\n\n"
        "Нетик — твій розумний кіногід 🎬\n"
        "Ось що я вмію:\n\n"
        "🔍 <b>Пошук</b> — просто напиши назву фільму\n"
        "🎃 <b>Добірка дня</b> — 5 фільмів від Нетика щодня\n"
        "🤖 <b>AI-рекомендація</b> — персональні поради\n"
        "🧠 <b>По настрою</b> — кіно під твій настрій\n"
        "🌿 <b>Мій список</b> — watchlist з категоріями\n"
        "🃏 <b>Свайп-режим</b> — гортай як у Tinder\n"
        "🎯 <b>Вгадай рейтинг</b> — грай та збирай бали\n"
        "👫 <b>Разом</b> — обирайте кіно вдвох\n\n"
        "<b>Команди:</b>\n"
        "/start — головне меню\n"
        "/search — пошук фільму\n"
        "/profile — твій профіль\n"
        "/donate — підтримати проект\n"
        "/admin — панель адміна\n\n"
        f"📢 Наш канал: @{channel}\n"
        "<i>Підпишись, щоб розблокувати всі функції!</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📢 Наш канал",
            url=f"https://t.me/{channel}",
        )],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  9. DONATE
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_donate")
@router.message(Command("donate"))
async def cb_menu_donate(event: types.Message | types.CallbackQuery):
    card = getattr(config, "MONO_CARD", "")
    name = getattr(config, "MONO_NAME", "Нетик")
    text = (
        "☕️ <b>Підтримати Нетика!</b>\n\n"
        "Я — незалежний проєкт, і твоя підтримка допоможе мені ставати розумнішим, "
        "швидшим та купувати більше API-токенів для рекомендацій.\n\n"
        f"💳 <b>Карта Monobank:</b>\n<code>{card}</code>\n"
        f"👤 <b>Отримувач:</b> {name}\n\n"
        "🏆 За будь-який донат ти отримаєш вічний бейдж <b>Спонсора</b> у профілі!"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я переказав(ла)!", callback_data="confirm_donate")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "confirm_donate")
async def confirm_donate(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    safe_name = html.escape(callback.from_user.full_name)
    safe_username = html.escape(callback.from_user.username or "—")

    admin_msg = (
        f"💰 <b>Новий запит на донат!</b>\n\n"
        f"Юзер: {safe_name} (@{safe_username})\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"Перевірте оплату та видайте статус в адмінці."
    )
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"adm_set:sponsor:{user_id}")],
        [InlineKeyboardButton(text="❌ Відхилити (немає оплати)", callback_data=f"adm_set:reject_donate:{user_id}")]
    ])

    for admin_id in config.ADMIN_IDS:
        try:
            await callback.bot.send_message(admin_id, admin_msg, reply_markup=admin_kb, parse_mode="HTML")
        except Exception:
            pass

    await callback.message.answer(
        "🙏 <b>Дякуємо!</b>\n\nВаш запит надіслано адміністратору. Після підтвердження "
        "у вашому профілі з'явиться статус спонсора 🏆.",
        parse_mode="HTML"
    )
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  10. REFERRAL
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_referral")
async def cb_menu_referral(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    bot_username = (await callback.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    referrals = await db.get_referral_count(user_id)

    text = (
        "🎁 <b>Реферальна програма</b>\n\n"
        f"Запрошуй друзів і отримуй бонуси!\n\n"
        f"🔗 Твоє посилання:\n<code>{ref_link}</code>\n\n"
        f"👥 Запрошено друзів: <b>{referrals}</b>\n\n"
        "<i>За кожного друга, який підпишеться на канал, ти отримуєш +50 балів!</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  11. 💌 СКРИНЬКА ЗВОРОТНОГО ЗВ'ЯЗКУ
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu_feedback")
async def cb_menu_feedback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    """Вхідна точка скриньки зворотного зв'язку."""
    await state.set_state(FeedbackStates.CHOOSING_TYPE)
    text = (
        "💌 <b>Скринька пропозицій</b>\n\n"
        "Обери тип повідомлення:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐛 Знайшов баг",        callback_data="feedback_type:bug")],
        [InlineKeyboardButton(text="💡 Пропозиція",          callback_data="feedback_type:suggestion")],
        [InlineKeyboardButton(text="💬 Інше",                callback_data="feedback_type:other")],
        [InlineKeyboardButton(text="◀️ Меню",               callback_data="feedback_cancel")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("feedback_type:"), FeedbackStates.CHOOSING_TYPE)
async def cb_feedback_type(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    fb_type = callback.data.split(":")[1]
    type_labels = {"bug": "🐛 Баг", "suggestion": "💡 Пропозиція", "other": "💬 Інше"}
    label = type_labels.get(fb_type, fb_type)

    await state.update_data(fb_type=fb_type)
    await state.set_state(FeedbackStates.WRITING_TEXT)

    text = (
        f"<b>{label}</b>\n\n"
        "Напиши своє повідомлення — я передам його адміну.\n\n"
        "<i>Можеш написати будь-що: опис проблеми, ідею, побажання.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="feedback_cancel")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.message(FeedbackStates.WRITING_TEXT)
async def handle_feedback_text(message: types.Message, state: FSMContext):
    """Отримує текст зворотного зв'язку, зберігає в БД та пересилає адміну."""
    data = await state.get_data()
    fb_type = data.get("fb_type", "other")
    user_id = message.from_user.id
    text = message.text.strip() if message.text else ""

    if not text:
        return await message.answer("Будь ласка, напиши текст повідомлення.")

    try:
        await db.save_feedback(user_id=user_id, fb_type=fb_type, text=text)
    except Exception as e:
        logger.error(f"save_feedback error: {e}")

    type_labels = {"bug": "🐛 Баг", "suggestion": "💡 Пропозиція", "other": "💬 Інше"}
    label = type_labels.get(fb_type, fb_type)
    user_info = message.from_user
    username_str = f"@{user_info.username}" if user_info.username else f"id:{user_id}"

    admin_text = (
        f"📬 <b>Нове повідомлення у скриньці</b>\n\n"
        f"Тип: {label}\n"
        f"Від: {username_str} ({user_info.full_name})\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"<b>Текст:</b>\n{html.escape(text)}"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, admin_text, parse_mode="HTML")
        except Exception:
            pass

    await state.clear()
    has_premium = await is_premium(user_id, message.bot)
    markup = get_main_menu_kb(has_premium)

    await message.answer(
        "✅ <b>Дякую! Твоє повідомлення отримано.</b>\n\n"
        "Адмін розгляне його найближчим часом.",
        parse_mode="HTML",
    )
    await message.answer("Повертаємось до меню 👇", reply_markup=markup)


@router.callback_query(F.data == "feedback_cancel")
async def cb_feedback_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    """Скасовує введення зворотного зв'язку."""
    await state.clear()
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)
    markup = get_main_menu_kb(has_premium)
    safe_name = html.escape(callback.from_user.first_name)
    try:
        await callback.message.edit_text(
            f"Привіт, {safe_name}! 👋\nЯ — <b>Нетик</b>, твій кіногід 🎬\nЩо шукаємо сьогодні?",
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"Привіт, {safe_name}! 👋\nЯ — <b>Нетик</b>, твій кіногід 🎬\nЩо шукаємо сьогодні?",
            reply_markup=markup,
            parse_mode="HTML",
        )
    await callback.answer()


# ── Топ фільмів за оцінками спільноти ─────────────────────────────────────

@router.callback_query(F.data == "menu_top_movies")
async def cb_top_movies(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    """Entry point for community top movies."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Тиждень",  callback_data="top_period:week"),
            InlineKeyboardButton(text="📆 Місяць",   callback_data="top_period:month"),
            InlineKeyboardButton(text="🏆 Всі часи", callback_data="top_period:all"),
        ],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(
            "🏆 <b>Топ фільмів за оцінками спільноти</b>\n\nОбери період:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "🏆 <b>Топ фільмів за оцінками спільноти</b>\n\nОбери період:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("top_period:"))
async def cb_top_movies_period(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    """Shows top movies for selected period."""
    period = callback.data.split(":")[1]
    await callback.answer("⏳ Завантажую...")
    top = await db.get_top_movies(period=period, limit=10)
    period_labels = {"week": "тижня", "month": "місяця", "all": "всіх часів"}
    label = period_labels.get(period, "всіх часів")

    if not top:
        text = f"🏆 <b>Топ {label}</b>\n\n📭 Поки немає достатньо оцінок.\nОцінюй фільми — і ти з'явишся тут!"
    else:
        text = f"🏆 <b>Топ {label} за версією глядачів</b>\n\n"
        # Fetch all details in parallel to avoid N+1 problem
        get_details = tmdb_service.get_movie_details
        tasks = [get_details(m["tmdb_id"]) for m in top]
        details_list = await asyncio.gather(*tasks, return_exceptions=True)

        medals = ["🥇", "🥈", "🥉"] + ["🎬"] * 7
        for i, (movie, details) in enumerate(zip(top, details_list)):
            tmdb_id = movie["tmdb_id"]
            avg = movie["avg_rating"]
            votes = movie["vote_count"]
            
            if isinstance(details, Exception) or not details:
                title = f"Фільм ID:{tmdb_id}"
                year_str = ""
            else:
                title = details.get("title") or details.get("original_title") or f"ID:{tmdb_id}"
                year = (details.get("release_date") or "")[:4]
                year_str = f" ({year})" if year else ""
            
            text += f"{medals[i]} <b>{html.escape(title)}</b>{year_str} — ⭐ {avg}/10 ({votes} оцінок)\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Тиждень",   callback_data="top_period:week"),
            InlineKeyboardButton(text="📆 Місяць",   callback_data="top_period:month"),
            InlineKeyboardButton(text="🏆 Всі часи", callback_data="top_period:all"),
        ],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ── Збереження цитати дня ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("savequote:"))
async def cb_save_quote(callback: types.CallbackQuery):
    """Зберігає цитату дня в обране користувача."""
    user_id = callback.from_user.id
    quote_key = callback.data.split(":", 1)[1]
    db_conn = await db._get_db()
    async with db_conn.execute(
        "SELECT content FROM channel_posts WHERE post_type='quote_cache' AND preview_text=?", 
        (quote_key,)
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return await callback.answer("❌ Цитату не знайдено", show_alert=True)
        try:
            data = json.loads(row[0])
            quote_text = data.get("q", "Цитата")
            film_name = data.get("f", "Фільм")
            tmdb_id = data.get("tid")
            existing = await db.get_saved_quotes(user_id)
            if any(q['quote_text'] == quote_text for q in existing):
                return await callback.answer("ℹ️ Вже збережено", show_alert=True)
            await db.save_quote(user_id, quote_text, film_name, tmdb_id)
            await callback.answer("✅ Додано в збережені")
        except Exception as e:
            logger.error(f"Error saving quote: {e}")
            await callback.answer("❌ Помилка збереження")

@router.callback_query(F.data == "my_saved_quotes")
async def cb_my_saved_quotes(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    """Показує список збережених цитат."""
    user_id = callback.from_user.id
    quotes = await db.get_saved_quotes(user_id, limit=15)
    if not quotes:
        text = "💬 <b>Мої цитати</b>\n\nУ вас немає збережених цитат."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Профіль", callback_data="menu_profile")]
        ])
    else:
        text = "📜 <b>Ваші цитати:</b>\n\n"
        keyboard_rows = []
        for q in quotes:
            film = html.escape(q.get("film_name", "Невідомий фільм"))
            text += f"🎬 <i>{film}</i>\n<blockquote>{html.escape(q['quote_text'])}</blockquote>\n\n"
            keyboard_rows.append([InlineKeyboardButton(text=f"🗑 Видалити #{q['id']}", callback_data=f"del_quote:{q['id']}")])
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Профіль", callback_data="menu_profile")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("del_quote:"))
async def cb_del_quote(callback: types.CallbackQuery):
    """Видаляє цитату."""
    user_id = callback.from_user.id
    quote_id = int(callback.data.split(":")[1])
    await db.delete_saved_quote(user_id, quote_id)
    await callback.answer("🗑 Видалено")
    await cb_my_saved_quotes(callback)
