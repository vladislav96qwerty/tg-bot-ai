import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, CallbackQuery
from cachetools import TTLCache

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, ttl: float = 0.5):
        # Cache for 0.5 seconds by default to prevent burst spam
        self.user_cache = TTLCache(maxsize=10000, ttl=ttl)
        # Separate cache for callback double-tap protection
        self.cb_cache = TTLCache(maxsize=10000, ttl=2.0)
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        user_id = user.id
        
        # 1. Double-tap protection for callbacks
        if isinstance(event, CallbackQuery):
            # Unique key for callback: user_id + message_id + callback_data
            cb_key = f"{user_id}:{event.message.message_id if event.message else 0}:{event.data}"
            if cb_key in self.cb_cache:
                return await event.answer() # Silently ignore double clicks
            self.cb_cache[cb_key] = True

        # 2. General throttling (rate limiting)
        if user_id in self.user_cache:
            if isinstance(event, CallbackQuery):
                await event.answer("⚡️ Зачекайте трішки!", show_alert=False)
            return
        
        self.user_cache[user_id] = True
        return await handler(event, data)
