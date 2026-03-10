import logging
import asyncio
import random
import json
import hashlib
import urllib.parse
from urllib.parse import quote_plus
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile

from src.config import config
from src.database.db import db
from src.services.ai import ai_service
from src.services.tmdb import tmdb_service
from src.services.prompts import (
    MORNING_POST_PROMPT,
    QUOTE_OF_DAY_PROMPT,
    HIDDEN_GEM_PROMPT,
    DAILY_PICKS_PROMPT,
    CONTROVERSIAL_POST_PROMPT,
    WEEKLY_SUMMARY_PROMPT,
    ACTOR_SPOTLIGHT_PROMPT,
    QUIZ_PROMPT,
    GUESS_MOVIE_PROMPT,
)
from src.services.image_generator import image_generator

logger = logging.getLogger(__name__)


def _escape_md(text: str) -> str:
    """Екранує Markdown-символи в AI-тексті."""
    if not text:
        return ""
    for ch in ['*', '_', '[', ']', '`']:
        text = text.replace(ch, f'\\{ch}')
    return text


async def _build_watch_keyboard(movie_id: int, title: str) -> InlineKeyboardMarkup | None:
    """
    Будує клавіатуру «Де дивитися» для постів у каналі.
    Якщо провайдери є — показує кнопки з посиланнями.
    Завжди додає fallback-кнопку JustWatch.
    Повертає None якщо щось пішло не так.
    """
    try:
        # ✅ FIX #1: передаємо title для fallback URL якщо TMDB поверне порожній link
        providers = await tmdb_service.get_watch_providers(movie_id, title=title)
        rows = []

        if providers:
            row = []
            for p in providers:
                btn = InlineKeyboardButton(text=f"{p['emoji']} {p['name']}", url=p["url"])
                row.append(btn)
                if len(row) == 2:
                    rows.append(row)
                    row = []
            if row:
                rows.append(row)

        # Завжди додаємо JustWatch як fallback
        fallback = f"https://www.justwatch.com/ua/search?q={quote_plus(title)}"
        rows.append([InlineKeyboardButton(
            text="🔍 Знайти на JustWatch",
            url=fallback,
        )])

        return InlineKeyboardMarkup(inline_keyboard=rows)
    except Exception as e:
        logger.error(f"_build_watch_keyboard error: {e}")
    return None


class ChannelScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

    def start(self):
        # Every day 09:00 — Morning movie post
        self.scheduler.add_job(self.post_morning_movie, "cron", hour=9, minute=0)

        # Mon 11:00 — Actor spotlight
        self.scheduler.add_job(self.post_actor_spotlight, "cron", day_of_week="mon", hour=11, minute=0)

        # Wed 19:00 — Cinematic quiz
        self.scheduler.add_job(self.post_quiz, "cron", day_of_week="wed", hour=19, minute=0)

        # Every day 13:00 — Quote of the day (Pillow card)
        self.scheduler.add_job(self.post_quote_of_day, "cron", hour=13, minute=0)

        # Tue & Thu 18:00 — Controversial hot take
        self.scheduler.add_job(self.post_controversial, "cron", day_of_week="tue,thu", hour=18, minute=0)

        # Thu 20:00 — Taste poll
        self.scheduler.add_job(self.post_taste_poll, "cron", day_of_week="thu", hour=20, minute=0)

        # Fri 17:00 — Hidden gem
        self.scheduler.add_job(self.post_hidden_gem, "cron", day_of_week="fri", hour=17, minute=0)

        # Sat 15:00 — Guess the movie (Question)
        self.scheduler.add_job(self.post_guess_movie, "cron", day_of_week="sat", hour=15, minute=0)

        # Sat 17:00 — Guess the movie (Answer)
        self.scheduler.add_job(self.post_guess_answer, "cron", day_of_week="sat", hour=17, minute=0)

        # Every day 21:00 — Daily picks
        self.scheduler.add_job(self.post_daily_picks, "cron", hour=21, minute=0)

        # Sun 12:00 — Weekly summary
        self.scheduler.add_job(self.post_weekly_summary, "cron", day_of_week="sun", hour=12, minute=0)

        self.scheduler.start()
        logger.info("Channel scheduler started.")

    async def _notify_admins(self, error_msg: str):
        """Notification for admins on scheduler failure."""
        for admin_id in config.ADMIN_IDS:
            try:
                await self.bot.send_message(
                    admin_id,
                    f"⚠️ <b>Scheduler Error</b>\n\n{error_msg}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Помилка сповіщення адміна: {e}")

    # ── 1. Morning Movie (09:00 daily) ─────────────────────────────────────

    async def post_morning_movie(self):
        try:
            movies = await tmdb_service.get_trending()
            if not movies:
                return logger.warning("post_morning_movie: no trending movies")

            movie = movies[0]
            movie_id = movie.get("id")
            title = movie.get("title", "Невідомий фільм")

            prompt = MORNING_POST_PROMPT.format(
                title=title,
                year=(movie.get("release_date") or "0000")[:4],
                genres=movie.get("genre_ids", []),
                rating=movie.get("vote_average", 0),
                overview=movie.get("overview") or "Опис відсутній.",
            )

            res = await ai_service.ask(prompt, expect_json=True)
            if not res or "post" not in res or "signature" not in res:
                await self._notify_admins("post_morning_movie: incomplete AI response")
                return logger.warning("post_morning_movie: incomplete AI response")

            text = f"{res['post']}\n\n{res['signature']}"


            keyboard = await _build_watch_keyboard(movie_id, title) if movie_id else None

            poster_url = tmdb_service.get_poster_url(movie.get("poster_path"))
            if poster_url:
                bot_msg = await self.bot.send_photo(
                    chat_id=config.CHANNEL_ID,
                    photo=poster_url,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            else:
                bot_msg = await self.bot.send_message(
                    chat_id=config.CHANNEL_ID,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            await db.save_channel_post("morning", res["post"][:100], text, movie_id, bot_msg.message_id)
            logger.info("Morning post sent.")
        except Exception as e:
            logger.error(f"post_morning_movie error: {e}", exc_info=True)
            await self._notify_admins(f"post_morning_movie error: {e}")

    # ── 2. Quote of the Day (13:00 daily) ──────────────────────────────────

    async def post_quote_of_day(self):
        try:
            res = await ai_service.ask(QUOTE_OF_DAY_PROMPT, expect_json=True)
            if not res or "quote_ua" not in res or "film" not in res:
                await self._notify_admins("post_quote_of_day: incomplete AI response")
                return logger.warning("post_quote_of_day: incomplete AI response")

            # ✅ FIX #Pillow: use asyncio.to_thread for synchronous image generation
            img_path = await asyncio.to_thread(
                image_generator.create_quote_card,
                res["quote_ua"],
                res.get("character") or res["film"]
            )

            caption = (
                f"🎬 *Цитата дня*\n\n"
                f"_{_escape_md(res['quote_ua'])}_\n\n"
                f"📌 {_escape_md(res['film'])} ({res.get('year', '')})\n"
                f"💡 {_escape_md(res.get('why_today', ''))}\n\n"
                f"@{config.CHANNEL_USERNAME.replace('@', '')}"
            )

            # Шукаємо фільм у TMDB для провайдерів
            keyboard = None
            film_tmdb_id = None
            try:
                results = await tmdb_service.search_movies(res["film"], limit=1)
                if results:
                    film_tmdb_id = results[0].get("id")
                    if film_tmdb_id:
                        keyboard = await _build_watch_keyboard(film_tmdb_id, res["film"])
            except Exception as e:
                logger.warning(f"post_quote_of_day: could not get providers: {e}")

            # ✅ FIX #2: прибрано мертвий код (quote_encoded/film_encoded/tmdb_part/перший save_btn)
            # Відразу будуємо правильний save_btn через md5-хеш
            try:
                quote_key = hashlib.md5(res["quote_ua"].encode()).hexdigest()[:8]
                save_btn = InlineKeyboardButton(
                    text="💬 Зберегти цитату",
                    callback_data=f"savequote:{quote_key}"
                )

                # ✅ FIX #3: json.dumps замість repr() → валідний JSON
                quote_data = json.dumps({
                    "q": res["quote_ua"][:200],
                    "f": res["film"][:80],
                    "tid": film_tmdb_id or 0
                }, ensure_ascii=False)

                # Зберігаємо цитату для пізнішого пошуку по ключу
                # ✅ FIX #4: тип "quote_cache" замість нестандартного "quote_data"
                await db.save_channel_post(
                    "quote_cache",
                    quote_key,
                    quote_data,
                    film_tmdb_id,
                    0
                )

                if keyboard:
                    existing_rows = keyboard.inline_keyboard
                    new_rows = existing_rows + [[save_btn]]
                    keyboard = InlineKeyboardMarkup(inline_keyboard=new_rows)
                else:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[[save_btn]])
            except Exception as e:
                logger.warning(f"post_quote_of_day: save_quote button error: {e}")

            bot_msg = await self.bot.send_photo(
                chat_id=config.CHANNEL_ID,
                photo=FSInputFile(img_path),
                caption=caption,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await db.save_channel_post("quote", res["quote_ua"][:100], caption, None, bot_msg.message_id)
            logger.info("Quote post sent.")
        except Exception as e:
            logger.error(f"post_quote_of_day error: {e}", exc_info=True)
            await self._notify_admins(f"post_quote_of_day error: {e}")

    # ── 3. Controversial Hot Take (Tue & Thu 18:00) ─────────────────────────

    async def post_controversial(self):
        """Overrated or underrated movie — provokes discussion."""
        try:
            movies = await tmdb_service.get_popular_movies(page=random.randint(1, 10))
            if not movies:
                return logger.warning("post_controversial: no movies")

            movie = random.choice(movies)
            movie_id = movie.get("id")
            title = movie.get("title", "Невідомий фільм")
            tmdb_rating = movie.get("vote_average", 5)

            # High-rated = potentially overrated, low-rated = potentially underrated
            post_type = "overrated" if tmdb_rating >= 7.5 else "underrated"

            prompt = CONTROVERSIAL_POST_PROMPT.format(
                title=title,
                year=(movie.get("release_date") or "0000")[:4],
                imdb_rating=tmdb_rating,
                post_type=post_type,
            )

            res = await ai_service.ask(prompt, expect_json=True)
            if not res or "headline" not in res or "argument" not in res:
                await self._notify_admins("post_controversial: incomplete AI response")
                return logger.warning("post_controversial: incomplete AI response")

            type_emoji = "📉" if post_type == "overrated" else "📈"
            type_label = "ПЕРЕОЦІНЕНО" if post_type == "overrated" else "НЕДООЦІНЕНО"

            text = (
                f"{type_emoji} *{type_label}*\n\n"
                f"🔥 *{_escape_md(res['headline'])}*\n\n"
                f"{_escape_md(res['argument'])}\n\n"
                f"🤔 {_escape_md(res.get('counterpoint', ''))}\n\n"
                f"💬 {_escape_md(res.get('question', ''))}\n\n"
                f"{_escape_md(res.get('signature', '— Нетик'))}"
            )

            keyboard = await _build_watch_keyboard(movie_id, title) if movie_id else None

            poster_url = tmdb_service.get_poster_url(movie.get("poster_path"))
            if poster_url:
                bot_msg = await self.bot.send_photo(
                    chat_id=config.CHANNEL_ID,
                    photo=poster_url,
                    caption=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            else:
                bot_msg = await self.bot.send_message(
                    chat_id=config.CHANNEL_ID,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )

            await db.save_channel_post("controversial", res["headline"][:100], text, movie_id, bot_msg.message_id)
            logger.info(f"Controversial post sent: {post_type}")
        except Exception as e:
            logger.error(f"post_controversial error: {e}", exc_info=True)
            await self._notify_admins(f"post_controversial error: {e}")

    # ── 4. Hidden Gem (Fri 17:00) ───────────────────────────────────────────

    async def post_hidden_gem(self):
        try:
            movies = await tmdb_service.get_popular_movies(page=random.randint(5, 15))
            if not movies:
                return logger.warning("post_hidden_gem: no movies")

            movie = random.choice(movies)
            movie_id = movie.get("id")
            title = movie.get("title", "Невідомий фільм")
            details = await tmdb_service.get_movie_details(movie_id)

            credits_data = await tmdb_service.get_movie_credits(movie_id)
            director = "Невідомий"
            for crew in credits_data.get("crew", []):
                if crew.get("job") == "Director":
                    director = crew["name"]
                    break

            prompt = HIDDEN_GEM_PROMPT.format(
                title=title,
                year=(movie.get("release_date") or "0000")[:4],
                genres=", ".join([g["name"] for g in details.get("genres", [])]),
                director=director,
                rating=movie.get("vote_average", 0),
                overview=movie.get("overview") or "Опис відсутній.",
            )

            res = await ai_service.ask(prompt, expect_json=True)
            if not res or "hook" not in res or "body" not in res:
                await self._notify_admins("post_hidden_gem: incomplete AI response")
                return logger.warning("post_hidden_gem: incomplete AI response")

            text = (
                f"💎 *Прихована перлина*\n\n"
                f"*{_escape_md(res['hook'])}*\n\n"
                f"{_escape_md(res['body'])}\n\n"
                f"✨ *Цікава деталь:* {_escape_md(res.get('best_moment', ''))}\n"
                f"🚫 *Не для тих...* {_escape_md(res.get('not_for_who', ''))}\n\n"
                f"{_escape_md(res.get('signature', '— Нетик'))}"
            )

            keyboard = await _build_watch_keyboard(movie_id, title) if movie_id else None

            poster_url = tmdb_service.get_poster_url(movie.get("poster_path"))
            if poster_url:
                bot_msg = await self.bot.send_photo(
                    chat_id=config.CHANNEL_ID,
                    photo=poster_url,
                    caption=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            else:
                bot_msg = await self.bot.send_message(
                    chat_id=config.CHANNEL_ID,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )

            await db.save_channel_post("hidden_gem", res["hook"][:100], text, movie_id, bot_msg.message_id)
            logger.info("Hidden gem post sent.")
        except Exception as e:
            logger.error(f"post_hidden_gem error: {e}", exc_info=True)
            await self._notify_admins(f"post_hidden_gem error: {e}")

    # ── 5. Daily Picks (21:00 daily) ────────────────────────────────────────

    async def post_daily_picks(self):
        try:
            popular_movies = await tmdb_service.get_popular(page=1)
            if not popular_movies:
                return logger.warning("post_daily_picks: no popular movies")

            movies_for_ai = [
                {
                    "id": m.get("id"),
                    "title": m.get("title"),
                    "year": (m.get("release_date") or "")[:4],
                    "overview": (m.get("overview") or "")[:100],
                }
                for m in popular_movies[:15]
            ]

            prompt = DAILY_PICKS_PROMPT.format(
                tmdb_movies_json=json.dumps(movies_for_ai, ensure_ascii=False)
            )
            content = await ai_service.ask(prompt, expect_json=True)

            if not content or "intro" not in content or "films" not in content:
                await self._notify_admins("post_daily_picks: AI returned incomplete content")
                return logger.warning("post_daily_picks: AI returned incomplete content")

            text = f"🎃 *Добірка дня від Нетика*\n\n{_escape_md(content['intro'])}\n\n"
            for film in content.get("films", []):
                text += f"{film.get('emoji', '🎬')} *{_escape_md(film.get('title_ua', 'Фільм'))}* — {_escape_md(film.get('pitch', ''))}\n\n"

            outro = content.get("outro", "")
            if outro:
                text += f"{_escape_md(outro)}\n\n"
            text += f"🎬 @{config.CHANNEL_USERNAME.replace('@', '')}"

            # Будуємо кнопки з першого фільму добірки
            keyboard = None
            try:
                first_film = content.get("films", [{}])[0]
                first_id = first_film.get("tmdb_id")
                first_title = first_film.get("title_ua", "")
                if first_id and first_title:
                    keyboard = await _build_watch_keyboard(int(first_id), first_title)
            except Exception as e:
                logger.warning(f"post_daily_picks: could not build keyboard: {e}")

            bot_msg = await self.bot.send_message(
                chat_id=config.CHANNEL_ID,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await db.save_daily_picks_cache(json.dumps(content, ensure_ascii=False))
            await db.save_channel_post("daily_picks", content["intro"][:100], text, None, bot_msg.message_id)
            logger.info("Daily picks post sent to channel.")
        except Exception as e:
            logger.error(f"post_daily_picks error: {e}", exc_info=True)
            await self._notify_admins(f"post_daily_picks error: {e}")

    # ── 6. Weekly Summary (Sun 12:00) ────────────────────────────────────────

    async def post_weekly_summary(self):
        """Weekly recap with stats, highlights and CTA."""
        try:
            stats = await db.get_weekly_stats()

            prompt = WEEKLY_SUMMARY_PROMPT.format(
                films_count=stats["films_count"],
                poll_winner=stats["poll_winner"],
                new_subs=stats["new_subs"],
                top_user=stats["top_user"],
            )

            res = await ai_service.ask(prompt, expect_json=True)
            if not res or "summary" not in res:
                await self._notify_admins("post_weekly_summary: incomplete AI response")
                return logger.warning("post_weekly_summary: incomplete AI response")

            text = (
                f"📊 *Підсумки тижня від Нетика*\n\n"
                f"{_escape_md(res['summary'])}\n\n"
                f"✨ {_escape_md(res.get('highlight', ''))}\n\n"
                f"{_escape_md(res.get('cta', ''))}\n\n"
                f"{_escape_md(res.get('signature', '— Нетик'))}\n\n"
                f"🎬 @{config.CHANNEL_USERNAME.replace('@', '')}"
            )

            bot_msg = await self.bot.send_message(
                chat_id=config.CHANNEL_ID,
                text=text,
                parse_mode="Markdown",
            )
            await db.save_channel_post("weekly_summary", res["summary"][:100], text, None, bot_msg.message_id)
            logger.info("Weekly summary post sent.")
        except Exception as e:
            logger.error(f"post_weekly_summary error: {e}", exc_info=True)
            await self._notify_admins(f"post_weekly_summary error: {e}")

    async def post_actor_spotlight(self):
        """Пн 11:00 — 'Актор тижня'."""
        try:
            # Знаходимо популярного актора (через трендінг або випадкового зі списку кращих)
            # Для простоти візьмемо когось із трендів TMDB
            actor = await tmdb_service.get_trending_person()
            if not actor:
                return logger.warning("post_actor_spotlight: no actor found")

            name = actor.get("name")
            prompt = ACTOR_SPOTLIGHT_PROMPT.format(name=name)
            res = await ai_service.ask(prompt, expect_json=True)
            if not res or "intro" not in res:
                return logger.warning("post_actor_spotlight: AI error")

            facts = "\n".join([f"🔹 {_escape_md(f)}" for f in res.get("facts", [])])
            movies = "\n".join([f"🎬 *{_escape_md(m)}*" for m in res.get("best_movies", [])])

            text = (
                f"🎭 *Актор тижня: {name}*\n\n"
                f"{_escape_md(res['intro'])}\n\n"
                f"*Цікаві факти:*\n{facts}\n\n"
                f"*Найкращі фільми:*\n{movies}\n\n"
                f"✨ {_escape_md(res.get('cta', ''))}\n\n"
                f"🎬 @{config.CHANNEL_USERNAME.replace('@', '')}"
            )

            photo_path = actor.get("profile_path")
            photo_url = f"https://image.tmdb.org/t/p/w500{photo_path}" if photo_path else None

            if photo_url:
                await self.bot.send_photo(chat_id=config.CHANNEL_ID, photo=photo_url, caption=text, parse_mode="Markdown")
            else:
                await self.bot.send_message(chat_id=config.CHANNEL_ID, text=text, parse_mode="Markdown")

            await db.save_channel_post("actor_spotlight", name, text, None, 0)
            logger.info(f"Actor spotlight post sent: {name}")
        except Exception as e:
            logger.error(f"post_actor_spotlight error: {e}", exc_info=True)

    async def post_quiz(self):
        """Ср 19:00 — Кіновікторина (Poll)."""
        try:
            res = await ai_service.ask(QUIZ_PROMPT, expect_json=True)
            if not res or "question" not in res:
                return logger.warning("post_quiz: AI error")

            options = [res["correct"], res["wrong1"], res["wrong2"], res["wrong3"]]
            # Shuffle options
            import random
            random.shuffle(options)
            correct_id = options.index(res["correct"])

            await self.bot.send_poll(
                chat_id=config.CHANNEL_ID,
                question=res["question"],
                options=options,
                type="quiz",
                correct_option_id=correct_id,
                explanation=_escape_md(res.get("explanation", "")),
                explanation_parse_mode="Markdown",
                is_anonymous=False
            )
            await db.save_channel_post("quiz", res["question"][:100], res["question"], None, 0)
            logger.info("Quiz post sent.")
        except Exception as e:
            logger.error(f"post_quiz error: {e}", exc_info=True)

    async def post_guess_movie(self):
        """Сб 15:00 — 'Впізнай фільм' (Питання)."""
        try:
            res = await ai_service.ask(GUESS_MOVIE_PROMPT, expect_json=True)
            if not res or "title" not in res:
                return logger.warning("post_guess_movie: AI error")

            # Шукаємо фільм у TMDB для постера
            search = await tmdb_service.search_movie(res["title"])
            if not search:
                return logger.warning(f"post_guess_movie: movie not found in TMDB: {res['title']}")

            movie = search[0]
            poster_path = movie.get("poster_path")
            poster_url = tmdb_service.get_poster_url(poster_path)

            text = (
                f"🧩 *Впізнай фільм за описом!*\n\n"
                f"1️⃣ {_escape_md(res['hint1'])}\n"
                f"2️⃣ {_escape_md(res['hint2'])}\n"
                f"3️⃣ {_escape_md(res['hint3'])}\n\n"
                f"💬 Пишіть ваші здогадки у коментарях! Відповідь буде за 2 години."
            )

            # Можна було б обрізати картинку, але AI-генератор поки не вміє "кропати" TMDB-постери.
            # Для MVP надішлемо розмиту картинку або просто текст + emoji.
            # Але краще згенерувати абстрактну картинку за жанром.
            # image_url = await image_generator.generate_image(f"Abstract cinematic art for {res['title']} movie theme")
            
            # Поки відправимо просто з емодзі, або якщо є постер - надішлемо його (але це спойлер).
            # Спробуємо надіслати без картинки або з генерованою.
            
            bot_msg = await self.bot.send_message(chat_id=config.CHANNEL_ID, text=text, parse_mode="Markdown")
            
            # Зберігаємо відповідь у базу, щоб post_guess_answer міг її дістати
            import json
            payload = json.dumps({
                "title": res["title"],
                "year": res["year"],
                "fun_fact": res["fun_fact"],
                "poster": poster_url
            })
            await db.save_channel_post("guess_movie_question", res["title"], payload, movie.get("id"), bot_msg.message_id)
            logger.info(f"Guess movie question sent: {res['title']}")
        except Exception as e:
            logger.error(f"post_guess_movie error: {e}", exc_info=True)

    async def post_guess_answer(self):
        """Сб 17:00 — 'Впізнай фільм' (Відповідь)."""
        try:
            # Дістаємо останнє питання
            last_q = await db.get_recent_post_by_type("guess_movie_question")
            if not last_q:
                return

            import json
            data = json.loads(last_q["text_full"]) # Ми зберегли JSON в text_full
            
            text = (
                f"✅ *Правильна відповідь: {data['title']} ({data['year']})*\n\n"
                f"💡 *Цікавий факт:* {_escape_md(data['fun_fact'])}\n\n"
                f"🎬 @{config.CHANNEL_USERNAME.replace('@', '')}"
            )

            keyboard = await _build_watch_keyboard(last_q["tmdb_id"], data["title"])

            if data.get("poster"):
                await self.bot.send_photo(
                    chat_id=config.CHANNEL_ID,
                    photo=data["poster"],
                    caption=text,
                    parse_mode="Markdown",
                    reply_to_message_id=last_q["message_id"],
                    reply_markup=keyboard
                )
            else:
                await self.bot.send_message(
                    chat_id=config.CHANNEL_ID,
                    text=text,
                    parse_mode="Markdown",
                    reply_to_message_id=last_q["message_id"],
                    reply_markup=keyboard
                )
            
            await db.save_channel_post("guess_movie_answer", data["title"], text, last_q["tmdb_id"], 0)
            logger.info(f"Guess movie answer sent: {data['title']}")
        except Exception as e:
            logger.error(f"post_guess_answer error: {e}", exc_info=True)

    async def post_taste_poll(self):
        """Чт 20:00 — Опитування про смаки."""
        try:
            questions = [
                "Який жанр сьогодні під настрій?",
                "Що краще: старе кіно чи новинки?",
                "Серіал на вечір чи повний метр?",
                "Який стрімінг ваш улюблений?"
            ]
            import random
            q = random.choice(questions)
            
            options = []
            if "жанр" in q:
                options = ["🍿 Бойовик", "😱 Жахи", "🎭 Драма", "🤡 Комедія"]
            elif "старе" in q:
                options = ["📽 Класика", "🆕 Тільки нове", "🌓 Під настрій"]
            elif "Серіал" in q:
                options = ["📺 Серіал", "🎬 Фільм", "🎞 Аніме"]
            else:
                options = ["Netflix", "HBO Max", "Disney+", "Apple TV+"]

            await self.bot.send_poll(
                chat_id=config.CHANNEL_ID,
                question=q,
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False
            )
            logger.info(f"Taste poll sent: {q}")
        except Exception as e:
            logger.error(f"post_taste_poll error: {e}", exc_info=True)