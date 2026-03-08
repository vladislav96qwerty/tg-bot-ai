import logging
from aiogram import Router
from aiogram.utils.deep_linking import create_start_link

router = Router()
logger = logging.getLogger(__name__)

# ✅ FIX: видалено дублікат @router.callback_query(F.data == "profile_referral")
# Цей хендлер є в profile.py і виконується першим — referrals.py ніколи не викликався.
# Залишаємо лише допоміжну функцію.

async def get_referral_link(bot, user_id: int) -> str:
    """Повертає реферальне посилання для користувача."""
    return await create_start_link(bot, f"ref_{user_id}", encode=False)