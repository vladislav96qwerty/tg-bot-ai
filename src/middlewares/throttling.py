import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, CallbackQuery
from cachetools import TTLCache

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, ttl: float = 0.5):
        # Cache for 0.5 seconds by default to prevent burst spam
        self.cache = TTLCache(maxsize=10000, ttl=ttl)
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
        
        # Simple check: if user_id in cache, it's a flood
        if user_id in self.cache:
            if isinstance(event, CallbackQuery):
                await event.answer("⚡️ Зачекайте трішки, занадто багато запитів!", show_alert=False)
            return
        
        self.cache[user_id] = True
        return await handler(event, data)
