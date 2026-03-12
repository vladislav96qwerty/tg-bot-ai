import logging
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from src.database.db import db
from src.routers.movie import is_premium
from src.config import config
from src.services.tmdb import tmdb_service

router = Router()
logger = logging.getLogger(__name__)


async def _render_watchlist(message: types.Message, user_id: int, status: str):
    items = await db.get_watchlist(user_id, status)
    status_map = {"want": "👀 Хочу дивитись", "watching": "▶️ Дивлюсь зараз", "watched": "✅ Переглянуто"}
    label = status_map.get(status, "Мій список")
    text = f"📂 *{label}* ({len(items)})\n\n"
    if not items:
        text += "_Тут поки порожньо..._"

    tabs = [
        InlineKeyboardButton(text="• 👀 Хочу •" if status=="want" else "👀 Хочу", callback_data="wl_tab:want"),
        InlineKeyboardButton(text="• ▶️ Дивлюсь •" if status=="watching" else "▶️ Дивлюсь", callback_data="wl_tab:watching"),
        InlineKeyboardButton(text="• ✅ Готово •" if status=="watched" else "✅ Готово", callback_data="wl_tab:watched"),
    ]
    keyboard = [tabs]
    for item in items[:10]:
        keyboard.append([InlineKeyboardButton(text=item["title_ua"], callback_data=f"wl_manage:{item['tmdb_id']}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")])
    try:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="Markdown")
    except Exception:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="Markdown")


async def _render_manage(message: types.Message, user_id: int, tmdb_id: int):
    item = await db.get_watchlist_item(user_id, tmdb_id)
    if not item:
        return await message.answer("Фільм не знайдено.")
    text = f"⚙️ *Керування:* {item['title_ua']}\nПоточний статус: _{item['status']}_"
    keyboard = [
        [InlineKeyboardButton(text="📋 Деталі", callback_data=f"movie_id:{tmdb_id}")],
        [InlineKeyboardButton(text="👀 Хочу", callback_data=f"wl_set:{tmdb_id}:want"),
         InlineKeyboardButton(text="▶️ Дивлюсь", callback_data=f"wl_set:{tmdb_id}:watching"),
         InlineKeyboardButton(text="✅ Готово", callback_data=f"wl_set:{tmdb_id}:watched")],
        [InlineKeyboardButton(text="🗑 Видалити", callback_data=f"wl_del:{tmdb_id}")],
        [InlineKeyboardButton(text="◀️ До списку", callback_data=f"wl_tab:{item['status']}")],
    ]
    try:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="Markdown")
    except Exception:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="Markdown")


@router.callback_query(F.data.startswith("wl_add:"))
async def cb_add_to_watchlist(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    tmdb_id = int(callback.data.split(":")[1])
    has_premium = await is_premium(user_id, callback.bot)
    if not has_premium:
        count = await db.get_watchlist_count(user_id)
        if count >= 1:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Підписатись", url=f"https://t.me/{config.CHANNEL_USERNAME.replace('@', '')}")],
                [InlineKeyboardButton(text="✅ Я підписався!", callback_data="subscribe_check")],
            ])
            await callback.answer()
            return await callback.message.answer("🔒 *Ліміт вичерпано!*\nБез підписки — 1 фільм у списку.", reply_markup=keyboard, parse_mode="Markdown")
    try:
        movie = await tmdb_service.get_movie_details(tmdb_id)
        title = movie.get("title", "Невідомий фільм")
        await db.add_to_watchlist(user_id, tmdb_id, title)
        await callback.answer(f"✅ Додано: {title}")
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        await callback.answer("⚠️ Помилка отримання даних фільму.", show_alert=True)




# ✅ FIX: "menu_watchlist" не містить ":" тому старий split(":")[1] міг дати IndexError
@router.callback_query(F.data == "menu_watchlist")
@router.callback_query(F.data.startswith("wl_tab:"))
async def cb_show_watchlist(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    # Використовуємо .split(":", 1) для безпечного парсингу
    parts = callback.data.split(":", 1)
    status = parts[1] if len(parts) > 1 else "want"

    await _render_watchlist(callback.message, user_id, status)
    await callback.answer()


@router.callback_query(F.data.startswith("wl_manage:"))
async def cb_manage_item(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    await _render_manage(callback.message, callback.from_user.id, int(callback.data.split(":")[1]))
    await callback.answer()


@router.callback_query(F.data.startswith("wl_set:"))
async def cb_update_status(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    _, tmdb_id, new_status = callback.data.split(":")
    await db.update_watchlist_status(callback.from_user.id, int(tmdb_id), new_status)
    await callback.answer("✅ Статус оновлено")
    await _render_manage(callback.message, callback.from_user.id, int(tmdb_id))


@router.callback_query(F.data.startswith("wl_del:"))
async def cb_delete_item(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    tmdb_id = int(callback.data.split(":")[1])
    await db.delete_from_watchlist(callback.from_user.id, tmdb_id)
    await callback.answer("🗑 Видалено")
    await _render_watchlist(callback.message, callback.from_user.id, "want")