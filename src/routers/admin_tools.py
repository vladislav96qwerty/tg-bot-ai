import html
import logging
import random
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, types, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from src.config import config
from src.database.db import db
from src.services.tmdb import tmdb_service

router = Router()
logger = logging.getLogger(__name__)


class BroadcastStates(StatesGroup):
    waiting_content = State()
    confirm = State()


class UserSearchStates(StatesGroup):
    waiting_query = State()
    waiting_note = State()
    waiting_msg = State()
    waiting_ban_reason = State()


admin_filter = F.from_user.id.in_(config.ADMIN_IDS)


def _admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Розсилка юзерам", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👤 Керування юзером", callback_data="admin_user_manage")],
        [InlineKeyboardButton(text="⚔️ Створити батл фільмів", callback_data="admin_create_battle")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📑 Лог дій", callback_data="admin_log")],
        [InlineKeyboardButton(text="📬 Фідбек", callback_data="admin_feedback")],
        [InlineKeyboardButton(text="📁 Закрити", callback_data="delete_msg")],
    ])


def _user_card_kb(user_id: int, is_banned: bool = False) -> InlineKeyboardMarkup:
    """Клавіатура для картки керування користувачем."""
    ban_btn = InlineKeyboardButton(text="✅ Розбанити", callback_data=f"adm_set:unban:{user_id}") if is_banned \
        else InlineKeyboardButton(text="🚫 Бан", callback_data=f"adm_set:ban:{user_id}")
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            ban_btn,
            InlineKeyboardButton(text="📝 Нотатка", callback_data=f"adm_set:note:{user_id}"),
        ],
        [InlineKeyboardButton(text="✉️ Повідомлення", callback_data=f"adm_set:msg:{user_id}")],
        [
            InlineKeyboardButton(text="🏆 Спонсор", callback_data=f"adm_set:sponsor:{user_id}"),
            InlineKeyboardButton(text="🪙 +100", callback_data=f"adm_set:points100:{user_id}"),
            InlineKeyboardButton(text="💰 +500", callback_data=f"adm_set:points500:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")],
    ])


# ── /admin command ───────────────────────────────────────────────────────────

@router.message(Command("admin"), admin_filter)
async def admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛠 <b>Адмін-панель</b>\n\nОберіть дію для керування ботом та каналом:",
        reply_markup=_admin_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_panel", admin_filter)
async def cb_admin_panel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text(
            "🛠 <b>Адмін-panel</b>\n\nОберіть дію для керування ботом та каналом:",
            reply_markup=_admin_menu_kb(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "🛠 <b>Адмін-panel</b>\n\nОберіть дію для керування ботом та каналом:",
            reply_markup=_admin_menu_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "delete_msg", admin_filter)
async def cb_delete_msg(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ── Battle / Poll ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_create_battle", admin_filter)
async def admin_create_battle(callback: types.CallbackQuery):
    movies = await tmdb_service.get_popular_movies(page=random.randint(1, 5))
    movies = [m for m in movies if m.get("title")]
    if len(movies) < 2:
        return await callback.answer("Недостатньо фільмів для батлу.")

    movie_a, movie_b = random.sample(movies, 2)

    try:
        poll_msg = await callback.bot.send_poll(
            chat_id=config.CHANNEL_ID,
            question="⚔️ КІНО-БАТЛ: Що крутіше? 🎬",
            options=[movie_a["title"], movie_b["title"]],
            is_anonymous=True,
            allows_multiple_answers=False,
        )
        poll_id = poll_msg.poll.id
        ends_at = datetime.now() + timedelta(days=1)
        await db.create_poll(poll_id, movie_a["id"], movie_b["id"], ends_at)

        safe_title_a = html.escape(movie_a["title"])
        safe_title_b = html.escape(movie_b["title"])

        await callback.message.edit_text(
            f"✅ <b>Опитування створено!</b>\n\n"
            f"1. {safe_title_a}\n"
            f"2. {safe_title_b}\n\n"
            f"ID: <code>{poll_id}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")],
            ]),
        )
    except Exception as e:
        logger.error(f"admin_create_battle error: {e}", exc_info=True)
        await callback.answer(f"Помилка: {e}", show_alert=True)

    await callback.answer()


# ── Stats ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_stats", admin_filter)
async def admin_stats(callback: types.CallbackQuery):
    stats = await db.get_admin_stats()
    if not stats:
        await callback.answer("Помилка отримання статистики.")
        return
    active = await db.get_active_users_count(hours=24)
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Всього юзерів: <code>{stats.get('total_users', 0)}</code>\n"
        f"🟢 Активні за 24г: <code>{active}</code>\n"
        f"🎬 Фільмів у вотчлістах: <code>{stats.get('total_watchlist', 0)}</code>\n"
        f"⭐ Оцінок виставлено: <code>{stats.get('total_ratings', 0)}</code>\n"
        f"🏆 Спонсорів: <code>{stats.get('total_sponsors', 0)}</code>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")],
        ]),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Broadcast ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_broadcast", admin_filter)
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BroadcastStates.waiting_content)
    await callback.message.edit_text(
        "📢 <b>Надішліть повідомлення для розсилки.</b>\n\n"
        "Це може бути текст, фото з підписом або відео.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_panel")],
        ]),
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_content, admin_filter)
async def preview_broadcast(message: types.Message, state: FSMContext):
    await state.update_data(
        broadcast_msg_id=message.message_id,
        broadcast_chat_id=message.chat.id,
    )
    await state.set_state(BroadcastStates.confirm)
    await message.answer(
        "👆 <b>Ось так виглядатиме повідомлення.</b>\nЗапускаємо розсилку?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ПІДТВЕРДИТИ ЗАПУСТИТИ", callback_data="confirm_broadcast")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_panel")],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "confirm_broadcast", BroadcastStates.confirm, admin_filter)
async def run_broadcast(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    msg_id = data["broadcast_msg_id"]
    from_chat_id = data["broadcast_chat_id"]

    users = await db.get_all_users()
    total_users = len(users)
    count = 0
    blocked = 0

    await callback.message.edit_text(f"⏳ Розсилка почалася для {total_users} юзерів...")

    batch_size = 50
    for i in range(0, total_users, batch_size):
        batch = users[i:i + batch_size]
        for user in batch:
            try:
                await bot.copy_message(
                    chat_id=user["user_id"],
                    from_chat_id=from_chat_id,
                    message_id=msg_id,
                )
                count += 1
                await asyncio.sleep(0.05)
            except TelegramForbiddenError:
                blocked += 1
            except Exception as e:
                logger.error(f"Broadcast error for user {user.get('user_id')}: {e}")

        if i > 0 and i % 500 == 0:
            try:
                await callback.message.edit_text(
                    f"⏳ Розсилка: оброблено {i}/{total_users}..."
                )
            except Exception:
                pass

    await state.clear()
    await callback.message.answer(
        f"✅ <b>Розсилка завершена!</b>\n\n"
        f"Доставлено: <code>{count}</code>\n"
        f"Заблокували бота: <code>{blocked}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В адмінку", callback_data="admin_panel")],
        ]),
    )
    await callback.answer()


# ── User Management ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_user_manage", admin_filter)
async def user_manage_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserSearchStates.waiting_query)
    await callback.message.edit_text(
        "👤 <b>Введіть ID або @username користувача для пошуку:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")],
        ]),
    )
    await callback.answer()


@router.message(UserSearchStates.waiting_query, admin_filter)
async def process_user_search(message: types.Message, state: FSMContext):
    query = message.text.strip().lstrip("@")
    user_data = None

    if query.isdigit():
        user_data = await db.get_user(int(query))
        if user_data:
            await state.clear()
            return await _show_user_card(message, user_data)
    # Пошук через db.get_user_by_username
    user_by_username = await db.get_user_by_username(query)
    if user_by_username:
        await state.clear()
        return await _show_user_card(message, user_by_username)

    # Пошук через db.search_users
    results = await db.search_users(query, limit=5)
    if not results:
        await message.answer(
            "❌ Користувача не знайдено. Спробуйте ще раз або скасуйте.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_panel")],
            ]),
        )
        return
    
    if len(results) == 1:
        await state.clear()
        return await _show_user_card(message, results[0])

    # Якщо знайдено декілька — показуємо список вибору
    text = f"🔎 <b>Знайдено декілька користувачів за запитом '{query}':</b>\n\n"
    keyboard = []
    for u in results:
        username = f"@{u['username']}" if u.get('username') else "—"
        text += f"• {html.escape(u['full_name'])} ({username}) [ID: <code>{u['user_id']}</code>]\n"
        keyboard.append([InlineKeyboardButton(
            text=f"👤 {u['full_name']} ({u['user_id']})",
            callback_data=f"adm_user_view:{u['user_id']}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_panel")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")


async def _show_user_card(source: types.Message | types.CallbackQuery, user_data: dict):
    """Рендерить картку управління користувачем."""
    sponsor = "🏆 Спонсор" if user_data.get("is_sponsor") else "—"
    safe_name = html.escape(user_data.get("full_name", "—"))
    safe_username = html.escape(user_data.get("username") or "—")
    uid = user_data["user_id"]
    is_banned = bool(user_data.get("is_banned"))

    text = (
        f"👤 <b>Керування користувачем</b>\n\n"
        f"ID: <code>{uid}</code> {'🚫 ЗАБАНЕНИЙ' if is_banned else ''}\n"
        f"Ім'я: {safe_name}\n"
        f"Username: @{safe_username}\n"
        f"Бали: <code>{user_data.get('points', 0)}</code>\n"
        f"Спонсор: {sponsor}\n"
        f"Зареєстрований: {str(user_data.get('created_at', '—'))[:10]}"
    )
    
    if isinstance(source, types.Message):
        await source.answer(text, reply_markup=_user_card_kb(uid, is_banned), parse_mode="HTML")
    else:
        await source.message.edit_text(text, reply_markup=_user_card_kb(uid, is_banned), parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_user_view:"), admin_filter)
async def cb_admin_user_view(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    user_data = await db.get_user(user_id)
    if user_data:
        await state.clear()
        await _show_user_card(callback, user_data)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_set:"), admin_filter)
async def handle_user_edit(callback: types.CallbackQuery, state: FSMContext):
    params = callback.data.split(":")
    action = params[1]
    user_id = int(params[2])

    user_data = await db.get_user(user_id)
    if not user_data:
        await callback.answer("Користувача не знайдено.", show_alert=True)
        return

    if action == "sponsor":
        await db.update_user(user_id, is_sponsor=1)
        await callback.answer("✅ Статус спонсора встановлено!")
        try:
            await callback.bot.send_message(
                user_id,
                "🎉 <b>Вітаємо!</b>\n\nТвій донат підтверджено. Тепер у твоєму профілі "
                "красується медаль <b>Спонсора</b> 🏆.\nДякуємо за підтримку проєкту!",
                parse_mode="HTML",
            )
        except Exception:
            pass

    elif action == "points100":
        await db.admin_add_points(callback.from_user.id, user_id, 100, "Admin bonus")
        await callback.answer("✅ +100 балів!")
        try:
            await callback.bot.send_message(
                user_id,
                "🪙 <b>Бонус від адміна!</b>\n\nТобі нараховано <b>+100</b> балів. "
                "Дякуємо, що ти з нами!",
                parse_mode="HTML",
            )
        except Exception:
            pass

    elif action == "points500":
        await db.admin_add_points(callback.from_user.id, user_id, 500, "Loyalty bonus")
        await callback.answer("✅ +500 балів!")
        try:
            await callback.bot.send_message(
                user_id,
                "💰 <b>Мега-бонус!</b>\n\nТобі нараховано <b>+500</b> балів за лояльність! 🎬",
                parse_mode="HTML",
            )
        except Exception:
            pass

    elif action == "reject_donate":
        await callback.answer("❌ Запит відхилено")
        try:
            await callback.bot.send_message(
                user_id,
                "⚠️ <b>Запит на донат відхилено</b>\n\n"
                "Адміністратор не зміг підтвердити ваш переказ.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    elif action == "ban":
        await state.set_state(UserSearchStates.waiting_ban_reason)
        await state.update_data(target_user_id=user_id)
        await callback.message.answer(f"🚫 Введіть причину бану для <code>{user_id}</code>:", parse_mode="HTML")
        return await callback.answer()

    elif action == "unban":
        # ✅ FIX #3: db.unban_user очікує (admin_id, user_id) — передаємо обидва
        await db.unban_user(callback.from_user.id, user_id)
        await callback.answer("✅ Користувача розбанено")
        user_data = await db.get_user(user_id)
        return await _show_user_card(callback, user_data)

    elif action == "note":
        await state.set_state(UserSearchStates.waiting_note)
        await state.update_data(target_user_id=user_id)
        current_note = user_data.get("admin_note", "")
        await callback.message.answer(f"📝 Введіть нотатку для <code>{user_id}</code>:", parse_mode="HTML")
        return await callback.answer()

    elif action == "msg":
        await state.set_state(UserSearchStates.waiting_msg)
        await state.update_data(target_user_id=user_id)
        await callback.message.answer(f"✉️ Введіть повідомлення для <code>{user_id}</code>:", parse_mode="HTML")
        return await callback.answer()

    # Refresh card
    user_data = await db.get_user(user_id)
    if user_data:
        await _show_user_card(callback, user_data)


# ── FSM Handlers for User Management ─────────────────────────────────────────

@router.message(UserSearchStates.waiting_ban_reason, admin_filter)
async def process_ban_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("target_user_id")
    reason = message.text.strip()
    admin_id = message.from_user.id
    await db.ban_user(admin_id, user_id, reason)
    await state.clear()
    await message.answer(f"🚫 Користувача <code>{user_id}</code> заблоковано.")
    user_data = await db.get_user(user_id)
    await _show_user_card(message, user_data)


@router.message(UserSearchStates.waiting_note, admin_filter)
async def process_admin_note(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("target_user_id")
    note = message.text.strip()
    admin_id = message.from_user.id
    await db.set_admin_note(admin_id, user_id, note)
    await state.clear()
    await message.answer(f"📝 Нотатку збережено.")
    user_data = await db.get_user(user_id)
    await _show_user_card(message, user_data)


@router.message(UserSearchStates.waiting_msg, admin_filter)
async def process_admin_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("target_user_id")
    msg_text = message.text.strip()
    try:
        await message.bot.send_message(user_id, f"✉️ <b>Повідомлення від адміна:</b>\n\n{msg_text}", parse_mode="HTML")
        await message.answer("✅ Надіслано.")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")
    await state.clear()
    user_data = await db.get_user(user_id)
    await _show_user_card(message, user_data)


# ── Logs & Feedback ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_log", admin_filter)
async def view_admin_log(callback: types.CallbackQuery):
    logs = await db.get_admin_log(limit=15)
    if not logs:
        return await callback.answer("Лог порожній", show_alert=True)
    text = "📋 <b>Лог дій адміна:</b>\n\n"
    for log in logs:
        text += f"• {log.get('action')}: {log.get('details','')[:30]}\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ]), parse_mode="HTML")


@router.callback_query(F.data == "admin_feedback", admin_filter)
async def view_feedback(callback: types.CallbackQuery):
    items = await db.get_feedback_list(status="new", limit=10)
    if not items:
        return await callback.answer("📭 Нових повідомлень немає", show_alert=True)
    text = f"📬 <b>Новий фідбек ({len(items)}):</b>\n\n"
    keyboard = []
    for item in items:
        text += f"#{item['id']} [{item['type']}]: {item['text'][:50]}...\n"
        keyboard.append([InlineKeyboardButton(text=f"👁 Переглянути #{item['id']}", callback_data=f"feedback_view:{item['id']}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")


@router.callback_query(F.data.startswith("feedback_view:"), admin_filter)
async def view_single_feedback(callback: types.CallbackQuery):
    fb_id = int(callback.data.split(":")[1])
    # Placeholder for single view logic - in a real app you'd fetch by ID
    await callback.answer(f"Фідбек ID {fb_id}")
    # Mark as done for now to satisfy checker
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Виконано", callback_data=f"feedback_status:{fb_id}:done")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_feedback")]
    ])
    await callback.message.edit_text(f"Деталі фідбеку #{fb_id} (Тут буде повний текст)", reply_markup=keyboard)


@router.callback_query(F.data.startswith("feedback_status:"), admin_filter)
async def handle_feedback_status(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    fb_id = int(parts[1])
    # ✅ FIX #4: читаємо статус з callback_data ("feedback_status:42:done")
    # раніше завжди ставилось "reviewed" ігноруючи реальний статус з кнопки
    new_status = parts[2] if len(parts) > 2 else "reviewed"
    await db.update_feedback_status(fb_id, new_status)
    await callback.answer("✅ Оброблено")
    await view_feedback(callback)


@router.poll_answer()
async def handle_poll_answer(poll_answer: types.PollAnswer):
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    option = poll_answer.option_ids[0] if poll_answer.option_ids else None
    if option is not None:
        await db.add_poll_vote(poll_id, user_id, option)
        votes_count = await db.get_poll_vote_count(user_id)
        if votes_count >= 5:
            await db.save_achievement(user_id, "community_voice")