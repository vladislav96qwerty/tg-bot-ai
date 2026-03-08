import html
import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from src.keyboards.main_menu import (
    get_onboarding_genres_kb,
    get_onboarding_frequency_kb,
    get_onboarding_period_kb,
    get_main_menu_kb
)
from src.database.db import db
from src.services.ai import ai_service
from src.services.prompts import RECOMMENDATION_PROMPT

router = Router()
logger = logging.getLogger(__name__)

class OnboardingStates(StatesGroup):
    GENRES = State()
    FREQUENCY = State()
    PERIOD = State()


async def start_onboarding(message: types.Message, state: FSMContext):
    """Entry point for onboarding, called from common.py or elsewhere."""
    await state.set_state(OnboardingStates.GENRES)
    await message.answer(
        "<b>Крок 1/3: Обери улюблені жанри (мін. 2):</b> 🎭",
        reply_markup=get_onboarding_genres_kb(set()),
        parse_mode="HTML",
    )


# FIX: added OnboardingStates.GENRES filter — prevents stale buttons from triggering
@router.callback_query(F.data.startswith("genre_"), OnboardingStates.GENRES)
async def cb_genre_select(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("genres", []))
    genre = callback.data.replace("genre_", "")

    if genre in selected:
        selected.remove(genre)
    else:
        selected.add(genre)

    await state.update_data(genres=list(selected))
    await callback.message.edit_reply_markup(reply_markup=get_onboarding_genres_kb(selected))
    await callback.answer()


@router.callback_query(F.data == "onboarding_genres_done", OnboardingStates.GENRES)
async def cb_genres_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("genres", [])

    if len(selected) < 2:
        return await callback.answer("🎬 Будь ласка, обери хоча б 2 жанри!", show_alert=True)

    await state.set_state(OnboardingStates.FREQUENCY)
    try:
        await callback.message.edit_text(
            "Крок 2/3: Як часто дивишся кіно? 🍿",
            reply_markup=get_onboarding_frequency_kb()
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("freq_"), OnboardingStates.FREQUENCY)
async def cb_freq_done(callback: types.CallbackQuery, state: FSMContext):
    freq = callback.data.replace("freq_", "")
    await state.update_data(frequency=freq)

    await state.set_state(OnboardingStates.PERIOD)
    await callback.message.edit_text(
        "Крок 3/3: Якому періоду надаєш перевагу? 🎞",
        reply_markup=get_onboarding_period_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("period_"), OnboardingStates.PERIOD)
async def cb_period_done(callback: types.CallbackQuery, state: FSMContext):
    period = callback.data.replace("period_", "")
    data = await state.get_data()
    genres = data.get("genres", [])
    frequency = data.get("frequency", "")

    user_id = callback.from_user.id

    # Save to DB
    await db.save_user_preferences(
        user_id=user_id,
        genres=genres,
        frequency=frequency,
        period=period
    )

    await callback.message.edit_text("⏳ Нетик аналізує твої смаки... Зачекай хвилинку.")

    # Generate AI taste profile
    ai_profile_prompt = (
        f"Ти — Нетик. На основі цих даних склади короткий 'смаковий профіль' юзера (до 30 слів). "
        f"Жанри: {', '.join(genres)}. Частота: {frequency}. Період: {period}."
    )
    ai_profile = await ai_service.ask(ai_profile_prompt, expect_json=False)

    if not ai_profile:
        ai_profile = "Твій кінопрофіль готовий! Я врахував твої вподобання."

    if ai_profile:
        await db.update_user_preferences(user_id, ai_taste_profile=ai_profile)

    await state.clear()

    safe_profile = html.escape(ai_profile or 'Кіноман-дослідник')
    welcome_back = (
        f"🎉 <b>Чудово! Тепер ми знайомі краще.</b>\n\n"
        f"Твій профіль: <i>{safe_profile}</i> 🎬\n\n"
        f"Користуйся меню нижче, щоб почати подорож!"
    )

    from src.routers.movie import is_premium
    has_premium = await is_premium(user_id, callback.bot)

    await callback.message.answer(welcome_back, reply_markup=get_main_menu_kb(has_premium), parse_mode="HTML")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()