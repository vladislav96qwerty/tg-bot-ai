import html
import logging
import json
import random
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from src.database.db import db
from src.services.tmdb import tmdb_service
from src.routers.movie import is_premium

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "menu_swipe")
async def start_swipe_session(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not await is_premium(user_id, callback.bot):
        return await callback.answer(
            "🔒 Свайп-режим доступний тільки підписникам!", show_alert=True
        )
    if not await db.get_swipe_session(user_id):
        prefs = await db.get_user_preferences(user_id)
        if not prefs:
            prefs = {"genres": [], "period": "any"}
        genres = prefs.get("genres")
        if not genres: # If genres is empty or None, use default string
            genres = "Бойовик,Комедія"
        # period = prefs.get("period", "any") # 'period' is not used in save_swipe_session here
        await db.save_swipe_session(user_id, genres, 0, json.dumps([]))
    await show_next_swipe(callback)


async def show_next_swipe(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    session = await db.get_swipe_session(user_id)
    if not session:
        return await callback.answer("Сесію не знайдено.", show_alert=True)
        
    movies = await tmdb_service.get_popular_movies(page=random.randint(1, 10))
    swiped_ids = json.loads(session.get("session_data") or "[]")
    available = [m for m in movies if m.get("id") not in swiped_ids]

    if not available:
        return await callback.message.edit_text(
            "🎉 Фільми закінчились! Спробуй пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
            ]),
        )

    movie = available[0]
    overview = movie.get("overview") or ""

    safe_title = html.escape(movie.get('title', '?'))
    text = (
        f"🃏 <b>СВАЙПАЛКА НЕТИКА</b>\n\n"
        f"🎬 <b>{safe_title}</b> ({(movie.get('release_date') or '0000')[:4]})\n"
        f"⭐ Рейтинг: {movie.get('vote_average', 0)}\n\n"
        f"{html.escape(overview[:200])}{'...' if len(overview) > 200 else ''}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👎", callback_data=f"swipe_dislike:{movie['id']}"),
            InlineKeyboardButton(text="👍", callback_data=f"swipe_like:{movie['id']}"),
        ],
        [InlineKeyboardButton(text="📋 Деталі", callback_data=f"movie_id:{movie['id']}")],
        [InlineKeyboardButton(text="🛑 Завершити", callback_data="back_to_menu")],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        poster_url = await tmdb_service.get_poster_url(movie.get("poster_path"))
        if poster_url:
            await callback.message.answer_photo(
                poster_url, caption=text, reply_markup=keyboard, parse_mode="HTML"
            )
        else:
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error showing swipe: {e}")
        await callback.message.answer("Помилка відображення фільму.")


@router.callback_query(F.data.startswith("swipe_"))
async def handle_swipe(callback: types.CallbackQuery):
    action, tmdb_id_str = callback.data.split(":")
    tmdb_id = int(tmdb_id_str)
    user_id = callback.from_user.id

    session = await db.get_swipe_session(user_id)
    if not session:
        # Assuming 'genres' is a string, 'last_movie_id' is int, 'session_data' is JSON string
        # The original save_swipe_session takes (user_id, genres, last_movie_id, session_data)
        # The provided snippet for save_swipe_session(user_id, "{}", datetime.now().isoformat())
        # does not match the signature of the existing save_swipe_session.
        # I will use default values that match the existing signature.
        await db.save_swipe_session(user_id, "Бойовик,Комедія", 0, json.dumps([]))
        session = await db.get_swipe_session(user_id)

    if not session:
        # If session is still None after attempting to create it, something is wrong.
        # The original code uses callback.message.edit_text or callback.answer.
        # Using callback.answer for consistency.
        await callback.answer("Помилка при створенні сесії.", show_alert=True)
        return

    # The original code uses 'session_data' key. The provided snippet uses 'history'.
    # Sticking to 'session_data' as per the existing code.
    swiped = json.loads(session.get("session_data") or "[]")
    if tmdb_id not in swiped:
        swiped.append(tmdb_id)
    await db.save_swipe_session(
        user_id, session.get("genres", ""), tmdb_id, json.dumps(swiped)
    )

    if action == "swipe_like":
        try:
            movie = await tmdb_service.get_movie_details(tmdb_id)
            title = movie.get("title", "Фільм")
            await db.add_to_watchlist(user_id, tmdb_id, title)
            await callback.answer(f"❤️ '{title}' у списку!")
        except Exception as e:
            logger.error(f"Error in swipe_like: {e}")
            await callback.answer("⚠️ Помилка додавання.", show_alert=True)
    else:
        await callback.answer("👎 Пропущено")

    await show_next_swipe(callback)