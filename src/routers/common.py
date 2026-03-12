import html
import logging
from aiogram import Router, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from datetime import datetime
from src.database.db import db
from src.config import config
from src.keyboards.main_menu import get_main_menu_kb
from src.routers.onboarding import OnboardingStates

router = Router()
logger = logging.getLogger(__name__)

PERSISTENT_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📙 Головне меню")]],
    resize_keyboard=True,
    is_persistent=True,
)


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject):
    await state.clear()
    user_id = message.from_user.id

    user = await db.get_user(user_id)
    is_new = not bool(user)
    if is_new:
        await db.create_user(
            user_id=user_id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            language_code=message.from_user.language_code,
        )

    if command.args:
        if command.args.startswith("ref_") and is_new:
            try:
                referrer_id = int(command.args.split("_")[1])
                if referrer_id != user_id:
                    await db.add_referral(referrer_id, user_id)
                    try:
                        await message.bot.send_message(
                            referrer_id,
                            "👥 Новий друг приєднався за твоїм посиланням! (+1 реферал)",
                        )
                    except Exception as e:
                        logger.debug(f"Failed to notify referrer: {e}")
            except (IndexError, ValueError) as e:
                logger.debug(f"Failed to parse deep link: {e}")

        elif command.args.startswith("joint_"):
            session_id = command.args.replace("joint_", "")
            await state.update_data(joint_session_id=session_id)
            prefs = await db.get_user_preferences(user_id)
            if prefs:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🚀 Почати свайпати разом!",
                        callback_data=f"joint_start:{session_id}",
                    )],
                    [InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu")],
                ])
                await message.answer(
                    f"👫 <b>Тебе запросили на спільний перегляд!</b>\n\nСесія: <code>{html.escape(session_id)}</code>",
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                return

    prefs = await db.get_user_preferences(user_id)
    if not prefs:
        from src.routers.onboarding import start_onboarding
        await message.answer(
            "Привіт! 👋\nЯ — <b>Нетик</b>, твій кіногід 🎬",
            reply_markup=PERSISTENT_MENU,
            parse_mode="HTML",
        )
        await start_onboarding(message, state)
        return

    await show_main_menu(message)


@router.message(Command("menu"))
@router.message(F.text == "📙 Головне меню")
async def cmd_menu(message: types.Message):
    await show_main_menu(message)


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    """Handler for /help command."""
    help_text = (
        "❓ <b>Допомога та команди</b>\n\n"
        "🎬 <b>Основне:</b>\n"
        "/start — Запустити бота\n"
        "/menu — Головне меню\n"
        "/search — Пошук фільмів\n\n"
        "👤 <b>Профіль:</b>\n"
        "/profile — Твій профіль та статистика\n"
        "/donate — Підтримати проект\n\n"
        "🤖 <b>Функції:</b>\n"
        "• AI-рекомендації під твій смак\n"
        "• Спільний вибір фільмів з другом\n"
        "• Свайп-режим для швидкого пошуку\n\n"
        "Якщо виникли питання — пишіть нашому адміністратору."
    )
    await message.answer(help_text, parse_mode="HTML")


@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: types.CallbackQuery, state: FSMContext = None):
    if not callback.message:
        await callback.answer()
        return
    if state:
        await state.clear()
    
    from src.routers.movie import is_premium

    user_id = callback.from_user.id
    has_premium = await is_premium(user_id, callback.bot)
    safe_name = html.escape(callback.from_user.first_name)
    menu_text = (
        f"Привіт, {safe_name}! 👋\n"
        f"Я — <b>Нетик</b>, твій кіногід 🎬\n"
        f"Що шукаємо сьогодні?"
    )
    markup = get_main_menu_kb(has_premium)

    if callback.message.photo or callback.message.video or callback.message.document:
        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug(f"Failed to delete old menu message: {e}")
        await callback.message.answer(menu_text, reply_markup=markup, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(menu_text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            try:
                await callback.message.edit_caption(caption=menu_text, reply_markup=markup, parse_mode="HTML")
            except Exception:
                await callback.message.answer(menu_text, reply_markup=markup, parse_mode="HTML")
                await callback.message.answer("Клавіатура оновлена ⬇️", reply_markup=PERSISTENT_MENU)
    await callback.answer()


@router.callback_query(F.data == "subscribe_check")
async def cb_subscribe_check_real(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    """Реальна перевірка підписки після натиснення «Я підписався»."""
    user_id = callback.from_user.id
    # Перевіряємо напряму через Telegram API, без кешу
    try:
        member = await callback.bot.get_chat_member(
            chat_id=config.CHANNEL_ID,
            user_id=user_id
        )
        is_sub = member.status in ["member", "administrator", "creator"]
        # Оновлюємо кеш після реальної перевірки
        from src.middlewares.subscription import invalidate_user_cache
        
        await db.update_user(
            user_id,
            channel_member_checked_at=datetime.now().isoformat(),
            channel_member_status="member" if is_sub else "left",
        )
        invalidate_user_cache(user_id)
    except Exception as e:
        logger.error(f"subscribe_check error: {e}")
        is_sub = False

    if is_sub:
        await callback.answer(
            "Дякуємо за підписку! ✅ Тепер тобі доступні всі Premium функції.",
            show_alert=True,
        )
        sub_text = "Привіт! 👋 Я Нетик — твій персональний гід у світі кіно.\n\nОбирай розділ нижче:"
        sub_kb = get_main_menu_kb(True)
        try:
            await callback.message.edit_text(sub_text, reply_markup=sub_kb, parse_mode="HTML")
        except Exception:
            try:
                await callback.message.edit_caption(caption=sub_text, reply_markup=sub_kb, parse_mode="HTML")
            except Exception:
                await callback.message.answer(sub_text, reply_markup=sub_kb, parse_mode="HTML")
    else:
        await callback.answer("Ви все ще не підписані на канал 📢", show_alert=True)


# ВИПРАВЛЕНО: noop залишається ТІЛЬКИ тут — дублікат у menu_handlers.py видалено.
# Цей хендлер зареєстрований першим (common.router включається першим у main.py).
@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


async def show_main_menu(message: types.Message):
    from src.routers.movie import is_premium

    has_premium = await is_premium(message.from_user.id, message.bot)
    safe_name = html.escape(message.from_user.first_name)
    
    menu_text = (
        f"Привіт, {safe_name}! 👋\n"
        f"Я — <b>Нетік</b>, твій кіногід 🎬\n"
        f"Що шукаємо сьогодні?"
    )
    
    # 1. Привітання + головне меню (Inline)
    await message.answer(
        menu_text,
        reply_markup=get_main_menu_kb(has_premium),
        parse_mode="HTML"
    )
    
    # 2. Активуємо нижню Reply-клавіатуру (Persistent)
    await message.answer(
        "Обери розділ або просто напиши назву фільму 👇",
        reply_markup=PERSISTENT_MENU,
        parse_mode="HTML"
    )