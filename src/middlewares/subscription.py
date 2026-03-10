import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Union

from aiogram import BaseMiddleware, Bot, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import config
from src.database.db import db

logger = logging.getLogger(__name__)


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, (types.Message, types.CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        # Whitelist — команди без перевірки підписки
        if isinstance(event, types.Message) and event.text:
            cmd = event.text.split()[0].lower()
            if cmd in ["/start", "/help", "/donate"]:
                return await handler(event, data)

        # Whitelist — колбеки без перевірки підписки
        if isinstance(event, types.CallbackQuery):
            if event.data in ["subscribe_check"]:
                return await handler(event, data)

        # Отримуємо користувача з БД
        user_db = await db.get_user(user.id)
        
        # Реєстрація нового користувача якщо немає в БД
        if not user_db:
            try:
                await db.create_user(
                    user_id=user.id,
                    username=user.username or "",
                    full_name=user.full_name,
                    language_code=user.language_code or "uk",
                )
                user_db = await db.get_user(user.id)
            except Exception as e:
                logger.error(f"Failed to create/fetch user {user.id}: {e}")
                return await handler(event, data)

        if not user_db:
            return await handler(event, data)

        # 🚫 ПЕРЕВІРКА БАНУ
        if await db.is_banned(user.id):
            user_db = await db.get_user(user.id) # Re-fetch to get reason
            ban_reason = user_db.get("ban_reason") or "" if user_db else ""
            msg = "🚫 <b>Ваш акаунт заблоковано.</b>"
            if ban_reason:
                msg += f"\nПричина: <i>{ban_reason}</i>"
            
            if isinstance(event, types.Message):
                await event.answer(msg, parse_mode="HTML")
            elif isinstance(event, types.CallbackQuery):
                await event.answer(msg.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""), show_alert=True)
            return

        bot: Bot = data["bot"]

        # Спонсори завжди мають доступ
        if user_db.get("is_sponsor") == 1:
            return await handler(event, data)

        # Перевірка кешу підписки (не частіше ніж раз на годину)
        last_checked_str = user_db.get("channel_member_checked_at")
        if last_checked_str:
            try:
                last_checked = datetime.fromisoformat(last_checked_str)
                if datetime.now() - last_checked < timedelta(hours=1):
                    if user_db.get("channel_member_status") == "member":
                        return await handler(event, data)
                    else:
                        await self._send_subscription_prompt(event, bot)
                        return None
            except (ValueError, TypeError) as e:
                logger.debug(f"Failed to parse last_checked_at: {e}")

        # Перевіряємо підписку через Telegram API
        is_subscribed = await self._check_subscription(bot, user.id)

        if is_subscribed:
            try:
                await db.update_user(
                    user.id,
                    channel_member_checked_at=datetime.now().isoformat(),
                    channel_member_status="member",
                )
            except Exception as e:
                logger.error(f"Помилка оновлення статусу підписки: {e}")
            return await handler(event, data)
        else:
            try:
                await db.update_user(
                    user.id,
                    channel_member_checked_at=datetime.now().isoformat(),
                    channel_member_status="left",
                )
            except Exception as e:
                logger.warning(f"Не вдалося оновити статус учасника: {e}")

        # Не підписаний — відправляємо запит
        await self._send_subscription_prompt(event, bot)
        return None

    async def _check_subscription(self, bot: Bot, user_id: int) -> bool:
        try:
            member = await bot.get_chat_member(
                chat_id=config.CHANNEL_ID,
                user_id=user_id,
            )
            return member.status in ["member", "administrator", "creator"]
        except Exception as e:
            logger.error(f"Subscription check error for user {user_id}: {e}")
            return False

    async def _send_subscription_prompt(
        self,
        event: Union[types.Message, types.CallbackQuery],
        bot: Bot,
    ) -> None:
        username = config.CHANNEL_USERNAME.replace("@", "")
        channel_url = f"https://t.me/{username}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📢 Підписатись і отримати доступ",
                url=channel_url,
            )],
            [InlineKeyboardButton(
                text="✅ Я підписався(лася)!",
                callback_data="subscribe_check",
            )],
        ])

        text = (
            "🎬 <b>Доступ обмежено</b>\n\n"
            "Нетик дарує безкоштовний преміум назавжди "
            "всім підписникам каналу!\n\n"
            "Підпишись щоб відкрити:\n"
            "✅ Персональні AI-рекомендації\n"
            "✅ Безлімітний Watchlist\n"
            "✅ Свайп-режим та багато іншого!"
        )

        if isinstance(event, types.Message):
            await event.answer(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            if event.message:
                try:
                    await event.message.edit_text(
                        text, reply_markup=keyboard, parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Помилка відправки повідомлення підписки: {e}")
            await event.answer(
                "Спочатку підпишись на канал! 🎬", show_alert=True
            )