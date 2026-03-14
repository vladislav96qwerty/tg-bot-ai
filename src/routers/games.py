import logging
import random
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from src.database.db import db
from src.services.tmdb import tmdb_service
from src.routers.movie import is_premium

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "menu_guess")
async def start_guess_game(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)

    if not has_premium:
        return await callback.answer("🔒 Гра доступна тільки підписникам каналу!", show_alert=True)

    # Get random popular movie
    movies = await tmdb_service.get_popular_movies(page=random.randint(1, 10))
    if not movies:
        return await callback.answer("Помилка отримання фільмів. Спробуйте пізніше.")

    # Filter only movies with real ratings
    movies = [m for m in movies if m.get('vote_average', 0) > 0 and m.get('poster_path')]
    if not movies:
        return await callback.answer("Помилка отримання фільмів. Спробуйте пізніше.")

    movie = random.choice(movies)
    poster_url = tmdb_service.get_poster_url(movie['poster_path'])
    rating = round(movie.get('vote_average', 0), 1)

    year = movie.get('release_date', '0000')[:4]
    import html
    text = (
        f"🎯 <b>Вгадай рейтинг TMDB</b>\n\n"
        f"🎬 <b>{html.escape(movie['title'])}</b> ({year})\n\n"
        f"Як думаєш, яку оцінку має цей фільм? 🤔"
    )

    # Передаємо рейтинг одразу в callback_data — без зайвого запиту до TMDB
    row1 = [
        InlineKeyboardButton(text=str(i), callback_data=f"guess_val:{movie['id']}:{i}")
        for i in range(1, 6)
    ]
    row2 = [
        InlineKeyboardButton(text=str(i), callback_data=f"guess_val:{movie['id']}:{i}")
        for i in range(6, 11)
    ]
    keyboard = [row1, row2, [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")]]

    try:
        await callback.message.delete()
    except Exception as e:
        logger.debug(f"Failed to delete message in guess game: {e}")

    await callback.answer()
    await callback.message.answer_photo(
        poster_url,
        caption=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("guess_val:"))
async def handle_guess(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    params = callback.data.split(":")
    if len(params) < 3:
        return await callback.answer("Невірні дані.")
    tmdb_id = int(params[1])
    guess = float(params[2])
    
    # SECURITY FIX: Fetch actual rating here, don't trust callback_data
    movie = await tmdb_service.get_movie_details(tmdb_id)
    actual = movie.get('vote_average', 0)
    user_id = callback.from_user.id

    diff = abs(guess - actual)

    if diff <= 0.5:
        points = 100
        message = "😱 *Неймовірно!* Ти вгадав(ла) майже ідеально! +100 балів 🏆"
        await db.save_achievement(user_id, "expert_eye")
    elif diff <= 1.0:
        points = 50
        message = "👏 *Чудово!* Дуже близько! +50 балів"
    elif diff <= 2.0:
        points = 20
        message = "👍 *Непогано!* Ти десь поруч. +20 балів"
    else:
        points = 0
        message = "🤷 *Мимо...* Не вгадав(ла). Спробуй ще! ❤️"

    if points > 0:
        await db.add_points(user_id, points)

    await db.save_rating_guess(user_id, tmdb_id, guess, actual, points)

    res_text = (
        f"📊 <b>Результат:</b>\n\n"
        f"Твій варіант: <code>{guess}</code>\n"
        f"Справжній рейтинг: <code>{actual}</code>\n\n"
        f"{message}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Ще раз", callback_data="menu_guess")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")],
    ])

    try:
        await callback.message.edit_caption(caption=res_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(res_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ── Емодзі-кіно 🧩 ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_emoji_game")
async def start_emoji_game(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)
    if not has_premium:
        return await callback.answer("🔒 Гра доступна тільки підписникам каналу!", show_alert=True)

    await callback.answer("🧩 Нетик загадує фільм...")

    # Беремо випадковий дуже популярний фільм
    movies = await tmdb_service.get_popular_movies(page=1)
    movie = random.choice(movies)

    from src.services.prompts import EMOJI_GAME_PROMPT
    prompt = EMOJI_GAME_PROMPT.format(
        title=movie.get("title"),
        year=(movie.get("release_date") or "")[:4]
    )
    res = await ai_service.ask(prompt, expect_json=True)
    if not res or "emojis" not in res:
        return await callback.answer("Помилка AI. Спробуйте ще раз.")

    text = (
        "🧩 <b>Вгадай фільм за емодзі!</b>\n\n"
        f"Загадка: {res['emojis']}\n"
        f"Підказка: <i>{res['hint']}</i>\n\n"
        "Натисни кнопку нижче, щоб побачити відповідь."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Показати відповідь", callback_data=f"emoji_ans:{movie['id']}")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.startswith("emoji_ans:"))
async def handle_emoji_answer(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        return await callback.answer("Помилка даних.")
    tmdb_id = int(parts[1])

    movie = await tmdb_service.get_movie_details(tmdb_id)
    title = movie.get("title") or movie.get("original_title")
    year = (movie.get("release_date") or "")[:4]

    text = (
        f"✅ <b>Це фільм: {title} ({year})</b>\n\n"
        "Вгадав(ла)? Якщо так — ти справжній кіноман! 😎"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Картка фільму", callback_data=f"movie_id:{tmdb_id}")],
        [InlineKeyboardButton(text="🔄 Ще раз", callback_data="menu_emoji_game")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")]
    ])

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()