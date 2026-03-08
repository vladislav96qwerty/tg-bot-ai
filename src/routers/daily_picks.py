import json
import logging
from datetime import datetime
from typing import List, Dict, Any

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.services.tmdb import tmdb_service
from src.services.ai import ai_service
from src.services.prompts import DAILY_PICKS_PROMPT
from src.database.db import db
from src.routers.movie import is_premium

router = Router()
logger = logging.getLogger(__name__)

# Ключ для окремого кешу добірки (відокремлено від channel_posts)
_CACHE_KEY = "daily_picks_json"


def _escape_md(text: str) -> str:
    """Екранує спецсимволи Markdown v1 у динамічному контенті."""
    if not text:
        return ""
    for ch in ["*", "_", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


async def get_daily_picks_content(force: bool = False) -> Dict[str, Any]:
    """
    Повертає кешовану добірку або генерує нову через AI.

    ВИПРАВЛЕНО: кеш зберігається окремим методом save_daily_picks_cache()
    який кладе JSON у поле content з post_type='daily_picks_cache'.
    Це відокремлює його від записів планувальника (post_type='daily_picks'),
    де content — готовий текст повідомлення, а не JSON.
    """
    if not force:
        cached = await db.get_recent_daily_picks_cache()
        if cached:
            try:
                parsed = json.loads(cached["content"])
                # Перевіряємо що це дійсно JSON-структура, а не текст посту
                if isinstance(parsed, dict) and "films" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                logger.warning("daily_picks cache corrupt, regenerating")

    # Генеруємо нову добірку
    popular_movies = await tmdb_service.get_popular(page=1)
    movies_for_ai = [
        {
            "id": m.get("id"),
            "title": m.get("title"),
            "year": m.get("release_date", "")[:4],
            "overview": m.get("overview", "")[:100],
        }
        for m in popular_movies[:15]
    ]

    prompt = DAILY_PICKS_PROMPT.format(
        tmdb_movies_json=json.dumps(movies_for_ai, ensure_ascii=False)
    )
    ai_response = await ai_service.ask(prompt, expect_json=True)

    if ai_response and isinstance(ai_response, dict) and "films" in ai_response:
        # ВИПРАВЛЕНО: зберігаємо JSON окремо з post_type='daily_picks_cache'
        await db.save_daily_picks_cache(json.dumps(ai_response, ensure_ascii=False))
        return ai_response

    return {}


@router.callback_query(F.data == "menu_daily_picks")
@router.callback_query(F.data == "refresh_daily_picks")
async def cb_daily_picks(callback: types.CallbackQuery):
    """Хендлер кнопки 'Добірка дня'."""
    is_refresh = callback.data == "refresh_daily_picks"
    user_id = callback.from_user.id

    if is_refresh:
        has_premium = await is_premium(user_id, callback.bot)
        if not has_premium:
            return await callback.answer(
                "🔄 Оновлення доступне лише підписникам каналу!", show_alert=True
            )
        await callback.answer("⏳ Оновлюю добірку...")
        picks = await get_daily_picks_content(force=True)
    else:
        await callback.answer()
        picks = await get_daily_picks_content(force=False)

    if not picks:
        return await callback.message.answer(
            "😔 Не вдалося сформувати добірку. Спробуйте пізніше."
        )

    intro = _escape_md(picks.get("intro", ""))
    outro = _escape_md(picks.get("outro", ""))

    text = "🎃 *Добірка дня від Нетика*\n\n"
    if intro:
        text += f"_{intro}_\n\n"

    keyboard = []
    for film in picks.get("films", []):
        emoji = film.get("emoji", "🎬")
        title = _escape_md(film.get("title_ua", "Фільм"))
        pitch = _escape_md(film.get("pitch", ""))
        tmdb_id = film.get("tmdb_id")

        text += f"{emoji} *{title}* — {pitch}\n\n"
        raw_title = film.get("title_ua", "Фільм")
        if tmdb_id:
            keyboard.append([InlineKeyboardButton(
                text=f"🎬 {raw_title}",
                callback_data=f"movie_id:{tmdb_id}",
            )])

    if outro:
        text += f"_{outro}_"

    keyboard.append([
        InlineKeyboardButton(text="🔄 Оновити", callback_data="refresh_daily_picks"),
        InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu"),
    ])

    await callback.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown",
    )
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete daily_picks msg: {e}")