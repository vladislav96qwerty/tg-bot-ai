import html
import uuid
import random
import logging
from aiogram import Router, F, types
from aiogram.utils.deep_linking import create_start_link
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from src.database.db import db
from src.services.tmdb import tmdb_service
from src.routers.movie import is_premium

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "menu_together")
async def joint_watch_menu(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    if not await is_premium(callback.from_user.id, callback.bot):
        return await callback.answer(
            "🔒 Спільний перегляд доступний тільки підписникам!", show_alert=True
        )
    
    text = (
        "👫 <b>Спільний перегляд</b>\n\n"
        "1. Створюєш сесію.\n2. Надсилаєш посилання другу.\n"
        "3. Ви обоє свайпаєте фільми.\n4. Мет'ч — коли обоє лайкнете один фільм! 🎯"
    )
    
    jw_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Створити сесію", callback_data="joint_create")],
        [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=jw_kb, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.edit_caption(caption=text, reply_markup=jw_kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=jw_kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "joint_create")
async def create_joint_session(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    try:
        session_id = str(uuid.uuid4())[:8]
        await db.create_watch_session(session_id, callback.from_user.id)
        link = await create_start_link(callback.bot, f"joint_{session_id}", encode=False)

        text = f"✅ <b>Сесію створено!</b>\n\nНадішли це посилання другу:\n<code>{link}</code>"
        
        jc_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📤 Надіслати",
                url=f"https://t.me/share/url?url={link}&text=Давай%20оберемо%20фільм%20разом!%20🍿",
            )],
            [InlineKeyboardButton(
                text="🚀 Почати свайпати",
                callback_data=f"joint_start:{session_id}",
            )],
            [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
        ])
        try:
            await callback.message.edit_text(text, reply_markup=jc_kb, parse_mode="HTML")
        except Exception:
            try:
                await callback.message.edit_caption(caption=text, reply_markup=jc_kb, parse_mode="HTML")
            except Exception:
                await callback.message.answer(text, reply_markup=jc_kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error creating joint session: {e}")
        err_jc_text = "❌ Помилка створення сесії. Спробуйте пізніше."
        err_jc_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")]
        ])
        try:
            await callback.message.edit_text(err_jc_text, reply_markup=err_jc_kb)
        except Exception:
            try:
                await callback.message.edit_caption(caption=err_jc_text, reply_markup=err_jc_kb)
            except Exception:
                await callback.message.answer(err_jc_text, reply_markup=err_jc_kb)
    finally:
        await callback.answer()


@router.callback_query(F.data.startswith("joint_start:"))
async def start_joint_swipe(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        return await callback.answer("❌ Невірний формат сесії", show_alert=True)
    session_id = parts[1]
    await show_next_joint_movie(callback, session_id)


async def show_next_joint_movie(callback: types.CallbackQuery, session_id: str):
    """Показати наступний фільм для спільного перегляду"""
    try:
        # Перевіряємо чи існує сесія
        session = await db.get_watch_session(session_id)
        if not session:
            no_js_text = "❌ Сесію не знайдено або вона завершена."
            no_js_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")]
            ])
            try:
                await callback.message.edit_text(no_js_text, reply_markup=no_js_kb)
            except Exception:
                try:
                    await callback.message.edit_caption(caption=no_js_text, reply_markup=no_js_kb)
                except Exception:
                    await callback.message.answer(no_js_text, reply_markup=no_js_kb)
            return

        # Get voted IDs for this user in this session
        voted_ids = await db.get_session_voted_ids(session_id, callback.from_user.id)
        
        # Filter available movies
        # Використовуємо хеш session_id для детермінованого вибору сторінки
        import hashlib
        page_seed = int(hashlib.md5(session_id.encode()).hexdigest(), 16) % 10 + 1
        movies = await tmdb_service.get_popular_movies(page=page_seed)
        available = [m for m in movies if m.get("id") not in voted_ids]
        
        if not available:
            no_av_text = "🎉 Ви переглянули всі популярні фільми! Чекайте на оновлення або спробуйте іншу категорію."
            no_av_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")]
            ])
            try:
                await callback.message.edit_text(no_av_text, reply_markup=no_av_kb)
            except Exception:
                try:
                    await callback.message.edit_caption(caption=no_av_text, reply_markup=no_av_kb)
                except Exception:
                    await callback.message.answer(no_av_text, reply_markup=no_av_kb)
            return

        movie = random.choice(available)
        overview = movie.get("overview") or ""

        safe_title = html.escape(movie.get('title', '?'))
        release_date = movie.get('release_date') or ''
        year = release_date[:4] if release_date else '????'
        
        text = (
            f"👫 <b>Спільний вибір</b> | <code>{html.escape(session_id)}</code>\n\n"
            f"🎬 <b>{safe_title}</b> ({year})\n"
            f"⭐ {movie.get('vote_average', 0)}/10\n\n"
            f"{html.escape(overview[:200])}..."
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👎", callback_data=f"joint_vote:{session_id}:{movie['id']}:0"
                ),
                InlineKeyboardButton(
                    text="👍", callback_data=f"joint_vote:{session_id}:{movie['id']}:1"
                ),
            ],
            [InlineKeyboardButton(text="🛑 Завершити", callback_data="back_to_menu")],
        ])
        
        old_msg = callback.message
        # Відправляємо з постером або без
        poster_url = tmdb_service.get_poster_url(movie.get("poster_path"))
        if poster_url:
            await callback.message.answer_photo(
                poster_url, 
                caption=text, 
                reply_markup=keyboard, 
                parse_mode="HTML"
            )
        else:
            await callback.message.answer(
                text, 
                reply_markup=keyboard, 
                parse_mode="HTML"
            )
            
        # Видаляємо попереднє повідомлення AFTER відправки нового
        try:
            await old_msg.delete()
        except Exception as e:
            logger.debug(f"Failed to delete old joint message: {e}")
            
    except Exception as e:
        logger.error(f"Error showing next joint movie: {e}")
        await callback.message.answer(
            "❌ Помилка завантаження фільму. Спробуйте пізніше.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")]
            ])
        )


@router.callback_query(F.data.startswith("joint_vote:"))
async def handle_joint_vote(callback: types.CallbackQuery):
    """Обробка голосування в спільній сесії"""
    if not callback.message:
        await callback.answer()
        return
    try:
        # Розбираємо callback_data
        parts = callback.data.split(":")
        if len(parts) != 4:
            return await callback.answer("❌ Помилка даних")
            
        _, session_id, tmdb_id_str, vote_str = parts
        tmdb_id = int(tmdb_id_str)
        vote = int(vote_str)
        user_id = callback.from_user.id

        # Перевіряємо чи існує сесія
        session = await db.get_watch_session(session_id)
        if not session:
            await callback.answer("❌ Сесію не знайдено", show_alert=True)
            return

        # Додаємо голос
        await db.add_session_vote(session_id, user_id, tmdb_id, vote)

        # Якщо це лайк, перевіряємо чи є метч
        if vote == 1:
            matches = await db.get_session_matches(session_id)
            if tmdb_id in matches:
                # Отримуємо деталі фільму
                movie = await tmdb_service.get_movie_details(tmdb_id)
                if movie:
                    match_text = (
                        f"🎉 <b>МЕТ'Ч!</b> 🎉\n\n"
                        f"Ви обоє хочете подивитися:\n"
                        f"🎬 <b>{html.escape(movie.get('title', '?'))}</b>\n\n"
                        f"🍿 Час готувати попкорн!"
                    )
                    
                    # Відправляємо повідомлення обом учасникам
                    await callback.message.answer(match_text, parse_mode="HTML")
                    
                    creator_id = session.get("creator_id")
                    if creator_id and creator_id != user_id:
                        try:
                            await callback.bot.send_message(
                                creator_id, match_text, parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify creator {creator_id}: {e}")
                    
                    await callback.answer("💖 МЕТ'Ч!", show_alert=True)
                    return
                    
            await callback.answer("👍 Лайк! Чекаємо на друга...")
        else:
            await callback.answer("👎 Пропущено")

        # Показуємо наступний фільм
        await show_next_joint_movie(callback, session_id)
        
    except ValueError as e:
        logger.error(f"Error parsing vote data: {e}")
        await callback.answer("❌ Помилка обробки голосу", show_alert=True)
    except Exception as e:
        logger.error(f"Error in handle_joint_vote: {e}")
        await callback.answer("❌ Сталася помилка", show_alert=True)