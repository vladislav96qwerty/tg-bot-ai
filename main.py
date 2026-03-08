import asyncio
import logging
import os
from aiohttp import web

from aiogram import Bot, Dispatcher

from src.config import config
from src.routers import (
    common,
    admin_tools,   # ← ВИПРАВЛЕНО: admin ПЕРЕД movie, щоб FSM-стани адміна
    movie,         #   не перехоплював text_search з movie.py
    onboarding,
    daily_picks,
    recommendations,
    watchlist,
    profile,
    referrals,
    swipe,
    joint_watch,
    games,
    menu_handlers,
)
from src.database.db import db
from src.middlewares.subscription import SubscriptionMiddleware
from src.services.scheduler import ChannelScheduler
from src.services.tmdb import tmdb_service

logger = logging.getLogger(__name__)

async def handle_health(request):
    return web.Response(text="Bot is running!")

async def run_dummy_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render assigns a dynamic PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Dummy web server started on port {port}")
    return runner


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    config.validate()
    await db.init_db()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    middleware = SubscriptionMiddleware()
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)

    # Порядок важливий: більш специфічні роутери — першими
    dp.include_router(common.router)
    dp.include_router(admin_tools.router)   # ВИПРАВЛЕНО: було останнім — тепер другим
    dp.include_router(movie.router)
    dp.include_router(onboarding.router)
    dp.include_router(daily_picks.router)
    dp.include_router(recommendations.router)
    dp.include_router(watchlist.router)
    dp.include_router(profile.router)
    dp.include_router(referrals.router)
    dp.include_router(swipe.router)
    dp.include_router(joint_watch.router)
    dp.include_router(games.router)
    dp.include_router(menu_handlers.router)

    scheduler = ChannelScheduler(bot)
    scheduler.start()

    logger.info("Starting dummy web server for Hugging Face healthchecks...")
    runner = await run_dummy_server()

    logger.info("Starting NeNetflixBot...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await db.close()
        await tmdb_service.close()
        logger.info("Bot stopped, resources released.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).info("Bot stopped!")