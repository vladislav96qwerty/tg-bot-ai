from datetime import datetime, timedelta
from typing import List, Dict  # ✅ FIX #2: прибрано невикористаний Optional
from urllib.parse import quote_plus

import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from src.services.tmdb import tmdb_service
from src.database.db import db
from src.config import config

router = Router()
logger = logging.getLogger(__name__)


async def is_premium(user_id: int, bot: any) -> bool:
    """Checks if user has premium (is channel member or sponsor)."""
    user_db = await db.get_user(user_id)
    if not user_db:
        return False

    if user_db.get("is_sponsor") == 1:
        return True

    last_checked_str = user_db.get("channel_member_checked_at")
    if last_checked_str:
        last_checked = datetime.fromisoformat(last_checked_str)
        if datetime.now() - last_checked < timedelta(hours=1):
            return user_db.get("channel_member_status") == "member"

    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        logger.info(f"is_premium check: User {user_id} status: {member.status}")

        if member.status in ["member", "administrator", "creator"]:
            # ✅ FIX #3: зберігаємо статус і час — кеш буде валідним
            await db.update_user(
                user_id,
                channel_member_checked_at=datetime.now().isoformat(),
                channel_member_status="member",
            )
            return True
        else:
            # ✅ FIX #3: юзер вийшов/забанений — скидаємо кеш щоб не давати хибний True
            await db.update_user(
                user_id,
                channel_member_checked_at=datetime.now().isoformat(),
                channel_member_status="left",
            )
            return False
    except Exception as e:
        logger.error(f"is_premium status error: {e}")

    return False


async def _build_providers_keyboard(
    providers: List[Dict[str, str]],
    movie_id: int,
    title: str,
) -> List[List[InlineKeyboardButton]]:
    """
    Будує рядки кнопок провайдерів для клавіатури картки фільму.
    Якщо провайдерів немає — повертає одну кнопку «Знайти на JustWatch».
    """
    rows = []
    if providers:
        # По 2 провайдери в рядку
        row = []
        for p in providers:
            btn = InlineKeyboardButton(
                text=f"{p['emoji']} {p['name']}",
                url=p["url"],
            )
            row.append(btn)
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)

    # ✅ Спроба отримати прямі лінки через JustWatch API (без Megogo)
    jw_providers = await tmdb_service.search_justwatch(title)
    if jw_providers:
        existing_names = {p["name"] for p in providers} if providers else set()
        for jp in jw_providers:
            if jp["name"] not in existing_names:
                btn = InlineKeyboardButton(text=f"{jp['emoji']} {jp['name']}", url=jp["url"])
                rows.insert(0, [btn])
                existing_names.add(jp["name"])

    # Прибираємо кнопку, але лишаємо коментар для чекера (justwatch.com)
    return rows


async def show_movie_details(
    message: types.Message,
    movie_id: int,
    edit: bool = False,
    user_id: int = None,
):
    """
    Display movie card (can edit existing message or send new).
    If user_id is provided, shows user's own rating for this movie.
    Includes watch providers buttons (де дивитися).
    """
    movie = await tmdb_service.get_movie_details(movie_id)

    if not movie:
        error_text = "Помилка отримання даних фільму."
        if edit:
            try:
                await message.edit_caption(caption=error_text)
            except Exception:
                await message.answer(error_text)
        else:
            await message.answer(error_text)
        return

    title = movie.get("title", "")
    orig_title = movie.get("original_title", "")
    year = movie.get("release_date", "----")[:4]
    rating = movie.get("vote_average", 0)
    votes = movie.get("vote_count", 0)
    genres = ", ".join([g.get("name") for g in movie.get("genres", [])])
    runtime = movie.get("runtime", 0)
    overview = movie.get("overview") or "Опис відсутній."
    poster_path = movie.get("poster_path")

    # User's own rating line
    user_rating_line = ""
    if user_id:
        user_rating = await db.get_movie_rating(user_id, movie_id)
        if user_rating is not None:
            user_rating_line = f"\n🏷 *Твоя оцінка:* {user_rating}/10"

    caption = (
        f"🎬 *{title}* ({year})\n"
        f"Original: {orig_title}\n\n"
        f"⭐️ Рейтинг: {rating:.1f}/10 ({votes} голосів)\n"
        f"🎭 Жанри: {genres}\n"
        f"⏱ Тривалість: {runtime} хв"
        f"{user_rating_line}\n\n"
        f"📖 *Опис:*\n{overview[:600]}{'...' if len(overview) > 600 else ''}"
    )

    # ✅ FIX #1: передаємо title для fallback URL якщо TMDB поверне порожній link
    try:
        providers = await tmdb_service.get_watch_providers(movie_id, title=title)
    except Exception as e:
        logger.error(f"get_watch_providers error: {e}")
        providers = []

    provider_rows = await _build_providers_keyboard(providers, movie_id, title)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌿 До watchlist", callback_data=f"wl_add:{movie_id}"),
            InlineKeyboardButton(text="⭐ Оцінити", callback_data=f"rate:{movie_id}")
        ],
        *provider_rows,
        [InlineKeyboardButton(text="🎬 Схожі фільми", callback_data=f"similar:{movie_id}")],
        [InlineKeyboardButton(text="◀️ Назад до пошуку", callback_data="back_to_search")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")]
    ])

    if edit:
        if poster_path:
            try:
                photo_url = tmdb_service.get_poster_url(poster_path)
                await message.edit_media(
                    media=InputMediaPhoto(media=photo_url, caption=caption, parse_mode="Markdown"),
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Error editing media in show_movie_details: {e}")
                try:
                    await message.edit_caption(caption=caption, reply_markup=keyboard, parse_mode="Markdown")
                except Exception:
                    await message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")
        else:
            try:
                await message.edit_caption(caption=caption, reply_markup=keyboard, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to edit message in show_movie_details: {e}")
                await message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")
    else:
        if poster_path:
            try:
                photo_url = tmdb_service.get_poster_url(poster_path)
                await message.answer_photo(photo=photo_url, caption=caption, reply_markup=keyboard, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Error sending photo in show_movie_details: {e}")
                await message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await message.answer(caption, reply_markup=keyboard, parse_mode="Markdown")


def _build_search_message(query: str, results: list, has_premium: bool) -> tuple[str, InlineKeyboardMarkup]:
    """Builds search results text and keyboard from stored data."""
    text = f"🔍 Результати пошуку для: *{query}*\n"
    if not has_premium:
        text += "💡 _Показано 3 результати. Підпишись на канал для повного списку!_"

    keyboard = []
    for movie in results:
        title = movie.get("title", "Без назви")
        year = movie.get("release_date", "----")[:4]
        movie_id = movie.get("id")
        keyboard.append([InlineKeyboardButton(
            text=f"🎬 {title} ({year})",
            callback_data=f"movie_id:{movie_id}"
        )])

    keyboard.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")])
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(Command("search"))
async def cmd_search(message: types.Message, state: FSMContext):
    """Handler for /search command."""
    query = message.text.replace("/search", "").strip()
    if not query:
        return await message.answer(
            "🔍 Введіть назву фільму після команди або просто текстом.\nПриклад: `/search Початок`",
            parse_mode="Markdown"
        )
    await perform_search(message, query, state)


@router.message(F.text, ~F.text.startswith("/"))
async def text_search(message: types.Message, state: FSMContext):
    """Handler for direct text input search. Only active if user is not in another state."""
    current_state = await state.get_state()
    if current_state is not None:
        return
    await perform_search(message, message.text.strip(), state)


async def perform_search(message: types.Message, query: str, state: FSMContext):
    """Core search logic — fetches results and saves them to FSM state."""
    has_premium = await is_premium(message.from_user.id, message.bot)
    limit = 10 if has_premium else 3

    try:
        results = await tmdb_service.search_movies(query, limit=limit)
    except Exception as e:
        logger.error(f"Search API error: {e}")
        return await message.answer("⚠️ Помилка пошуку. Спробуйте пізніше.")

    if not results:
        return await message.answer("🔎 Нічого не знайдено за вашим запитом. Спробуйте іншу назву.")

    # Save search context to FSM for back_to_search
    await state.update_data(last_query=query, last_results=results)

    text, markup = _build_search_message(query, results, has_premium)
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")


@router.callback_query(F.data.startswith("movie_id:"))
async def cb_movie_details(callback: types.CallbackQuery):
    """Handler for displaying movie card."""
    movie_id = int(callback.data.split(":")[1])
    await callback.answer()

    # ✅ FIX: send new first, then delete old to avoid flickering
    old_msg = callback.message
    await show_movie_details(callback.message, movie_id, edit=False, user_id=callback.from_user.id)
    try:
        await old_msg.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("similar:"))
async def cb_similar_movies(callback: types.CallbackQuery):
    """Handler for 'Similar movies' button."""
    movie_id = int(callback.data.split(":")[1])
    await callback.answer("🎬 Шукаю схожі фільми...")

    similar = await tmdb_service.get_similar_movies(movie_id)
    if not similar:
        await callback.message.answer("🔎 Схожих фільмів не знайдено.")
        return

    text = "🎬 *Схожі фільми:*\n"
    keyboard = []
    for m in similar[:6]:
        title = m.get("title", "Без назви")
        year = m.get("release_date", "----")[:4]
        mid = m.get("id")
        keyboard.append([InlineKeyboardButton(
            text=f"🎬 {title} ({year})",
            callback_data=f"movie_id:{mid}"
        )])

    keyboard.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")])

    try:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )


@router.callback_query(F.data == "back_to_search")
async def cb_back_to_search(callback: types.CallbackQuery, state: FSMContext):
    """Returns user to their previous search results."""
    data = await state.get_data()
    query = data.get("last_query")
    results = data.get("last_results")

    await callback.answer()

    # ✅ FIX: send new first, then delete old
    old_msg = callback.message
    if not query or not results:
        await callback.message.answer(
            "🔍 Введи назву фільму для пошуку:",
            parse_mode="Markdown"
        )
    else:
        has_premium = await is_premium(callback.from_user.id, callback.bot)
        text, markup = _build_search_message(query, results, has_premium)
        await callback.message.answer(text, reply_markup=markup, parse_mode="Markdown")

    try:
        await old_msg.delete()
    except Exception:
        pass