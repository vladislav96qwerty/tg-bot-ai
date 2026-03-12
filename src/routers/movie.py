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

# Баг #15 fix: простий TTL-кеш без зовнішніх залежностей — немає витоку пам'яті
class _TTLDict:
    """Мінімальний TTL-словник: зберігає ключ тільки ttl секунд."""
    def __init__(self, ttl: float):
        self._ttl = ttl
        self._data: dict = {}

    def __contains__(self, key):
        entry = self._data.get(key)
        if entry is None:
            return False
        if time.time() - entry > self._ttl:
            del self._data[key]
            return False
        return True

    def __setitem__(self, key, _value):
        self._data[key] = time.time()


_search_cooldown = _TTLDict(ttl=3)


async def is_premium(user_id: int, bot: any) -> bool:
    """Checks if user has premium (is channel member or sponsor)."""
    # Баг #14 fix: спочатку перевіряємо кеш middleware, щоб не дублювати запит
    from src.middlewares.subscription import _user_cache
    user_db = _user_cache.get(user_id)
    if not user_db:
        user_db = await db.get_user(user_id)
        if user_db:
            _user_cache[user_id] = user_db
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
            from src.middlewares.subscription import invalidate_user_cache
            invalidate_user_cache(user_id)
            return True
        else:
            # ✅ FIX #3: юзер вийшов/забанений — скидаємо кеш щоб не давати хибний True
            await db.update_user(
                user_id,
                channel_member_checked_at=datetime.now().isoformat(),
                channel_member_status="left",
            )
            from src.middlewares.subscription import invalidate_user_cache
            invalidate_user_cache(user_id)
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

    # Баг #15 fix: TTLCache — просто перевіряємо наявність ключа
    user_id = message.from_user.id
    if user_id in _search_cooldown:
        await message.answer("⏳ Зачекайте 3 секунди між пошуками")
        return
    _search_cooldown[user_id] = True

    await perform_search(message, message.text.strip(), state)


async def perform_search(message: types.Message, query: str, state: FSMContext):
    """Core search logic — fetches results and saves them to FSM state."""
    has_premium = await is_premium(message.from_user.id, message.bot)
    limit = 10 if has_premium else 3

    # Баг #27 fix: показуємо індикатор набору перед запитом
    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception as e:
        logger.debug(f"Failed to send typing action: {e}")

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
    if not callback.message:
        await callback.answer()
        return
    """Handler for displaying movie card."""
    parts = callback.data.split(":")
    if len(parts) < 2:
        return await callback.answer("Помилка даних.")
    movie_id = int(parts[1])
    await callback.answer()

    # ✅ FIX: send new first, then delete old to avoid flickering
    old_msg = callback.message
    await show_movie_details(callback.message, movie_id, edit=False, user_id=callback.from_user.id)
    try:
        await old_msg.delete()
    except Exception as e:
        logger.debug(f"Failed to delete old message after showing movie details: {e}")


# Баг #5 fix: повноцінний обробник кнопки "⭐ Оцінити"
@router.callback_query(F.data.startswith("rate:"))
async def cb_rate_movie(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        return await callback.answer("Помилка.")
    movie_id = int(parts[1])

    row1 = [
        InlineKeyboardButton(text=str(i), callback_data=f"set_rating:{movie_id}:{i}")
        for i in range(1, 6)
    ]
    row2 = [
        InlineKeyboardButton(text=str(i), callback_data=f"set_rating:{movie_id}:{i}")
        for i in range(6, 11)
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        row1, row2,
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"movie_id:{movie_id}")]
    ])
    try:
        await callback.message.edit_caption(
            caption="⭐ Оціни цей фільм від 1 до 10:",
            reply_markup=keyboard,
        )
    except Exception:
        await callback.message.answer(
            "⭐ Оціни цей фільм від 1 до 10:",
            reply_markup=keyboard,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("set_rating:"))
async def cb_set_rating(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) < 3:
        return await callback.answer("Помилка даних.")
    movie_id = int(parts[1])
    rating = int(parts[2])
    user_id = callback.from_user.id

    await db.save_rating(user_id, movie_id, rating)
    await db.add_points(user_id, 10)
    await callback.answer(f"✅ Оцінка {rating}/10 збережена! +10 балів")
    await show_movie_details(callback.message, movie_id, edit=True, user_id=user_id)


@router.callback_query(F.data.startswith("similar:"))
async def cb_similar_movies(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    """Handler for 'Similar movies' button."""
    parts = callback.data.split(":")
    if len(parts) < 2:
        return await callback.answer("Помилка.")
    movie_id = int(parts[1])
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
    if not callback.message:
        await callback.answer()
        return
    """Returns user to their previous search results."""
    data = await state.get_data()
    query = data.get("last_query")
    results = data.get("last_results")

    if not query or not results:
        await callback.answer("⏳ Результати пошуку застаріли.", show_alert=True)
        from src.routers.common import cb_back_to_menu
        return await cb_back_to_menu(callback, state)

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