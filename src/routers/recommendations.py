import logging
from typing import List, Dict, Any

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.services.recommender import recommender_service
from src.services.tmdb import tmdb_service
from src.routers.movie import is_premium, show_movie_details
from src.config import config

router = Router()
logger = logging.getLogger(__name__)

class RecommendationStates(StatesGroup):
    VIEWING = State()


@router.callback_query(F.data == "menu_ai_rec")
async def cb_ai_recommendations(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return
    """Handler for 'AI Recommendation' menu button."""
    user_id = callback.from_user.id
    
    # PREMIUM CHECK
    has_premium = await is_premium(user_id, callback.bot)
    if not has_premium:
        text = (
            "🔒 <b>Персональні AI-рекомендації — це Premium функція.</b>\n\n"
            "Нетик проаналізує твої смаки, оцінки та настрій, щоб підібрати ідеальне кіно.\n\n"
            "Підпишись на наш канал, щоб розблокувати цей розділ!"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Підписатись на канал", url=f"https://t.me/{config.CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton(text="I Підписався! ✅", callback_data="subscribe_check")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_menu")]
        ])
        return await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await callback.answer()
    rec_wait_text = "🤖 <b>Нетик вимикає логіку і вмикає інтуїцію...</b>\nАналізую твої смаки, зачекай трішки."
    try:
        await callback.message.edit_text(rec_wait_text, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.edit_caption(caption=rec_wait_text, parse_mode="HTML")
        except Exception:
            await callback.message.answer(rec_wait_text, parse_mode="HTML")
    try:
        await callback.bot.send_chat_action(chat_id=callback.from_user.id, action="typing")
    except Exception as e:
        logger.debug(f"Failed to send typing action: {e}")

    recs = await recommender_service.get_recommendations(user_id)

    if not recs:
        no_rec_text = "😔 Нетик поки не зміг підібрати нічого особливого. Спробуй оцінити більше фільмів!"
        no_rec_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu")]])
        try:
            await callback.message.edit_text(no_rec_text, reply_markup=no_rec_kb)
        except Exception:
            try:
                await callback.message.edit_caption(caption=no_rec_text, reply_markup=no_rec_kb)
            except Exception:
                await callback.message.answer(no_rec_text, reply_markup=no_rec_kb)
        return

    await state.set_state(RecommendationStates.VIEWING)
    await state.update_data(ai_recs=recs, current_index=0)

    await show_recommendation_card(callback.message, recs[0], 0, len(recs))

async def show_recommendation_card(message: types.Message, movie: Dict[str, Any], index: int, total: int):
    """Displays a single recommendation card."""
    
    title = movie.get("title_ua")
    year = movie.get("year")
    tmdb_rating = movie.get("tmdb_rating", 0)
    why = movie.get("why", "")
    hook = movie.get("hook", "")
    netyk_says = movie.get("netyk_says", "")
    tmdb_id = movie.get("tmdb_id")
    poster_path = movie.get("poster_path")
    
    text = (
        f"🤖 <b>AI-Порада ({index + 1}/{total})</b>\n\n"
        f"🎬 <b>{title}</b> ({year})\n"
        f"⭐️ Рейтинг TMDB: {tmdb_rating:.1f}/10\n\n"
        f"💡 <b>Чому варто глянути:</b>\n{why}\n\n"
        f"✨ <b>{hook}</b>\n\n"
        f"<i>{netyk_says}</i>"
    )
    
    keyboard = []
    # Action buttons
    action_row = []
    if tmdb_id:
        action_row.append(InlineKeyboardButton(text="🍿 До watchlist", callback_data=f"wl_add:{tmdb_id}"))
        action_row.append(InlineKeyboardButton(text="⭐ Оцінити", callback_data=f"rate:{tmdb_id}"))
    keyboard.append(action_row)
    
    # Navigation row
    nav_row = []
    if index < total - 1:
        nav_row.append(InlineKeyboardButton(text="➡️ Наступна", callback_data="next_ai_rec"))
    nav_row.append(InlineKeyboardButton(text="⬅️ Меню", callback_data="back_to_menu"))
    keyboard.append(nav_row)
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    if poster_path:
        photo_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        await message.answer_photo(photo=photo_url, caption=text, reply_markup=markup, parse_mode="HTML")
        try:
            await message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete message after showing recommendation: {e}")
    else:
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            try:
                await message.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            except Exception:
                await message.answer(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "next_ai_rec")
async def cb_next_ai_rec(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return

    current_state = await state.get_state()
    data = await state.get_data()
    recs = data.get("ai_recs", [])

    if current_state != RecommendationStates.VIEWING or not recs:
        await callback.answer("⏳ Сесія рекомендацій застаріла. Оновіть меню.", show_alert=True)
        from src.routers.common import cb_back_to_menu
        return await cb_back_to_menu(callback, state)

    index = data.get("current_index", 0) + 1

    if index < len(recs):
        await state.update_data(current_index=index)
        await show_recommendation_card(callback.message, recs[index], index, len(recs))
        await callback.answer()
    else:
        await state.clear()
        await callback.answer("Це була остання порада!")
