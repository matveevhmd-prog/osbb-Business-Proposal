import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import load_config
from database.fsm_storage import SqliteStorage
from database.models import init_db
from scheduler.jobs import register_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    await init_db()
    logger.info("Database initialised")

    # Ensure Google credentials are valid before the bot starts.
    # On first run this opens a browser; afterwards it silently refreshes the token.
    from sheets.auth import get_credentials
    await asyncio.to_thread(get_credentials, config)
    logger.info("Google credentials ready")

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = SqliteStorage("data/fsm_storage.db")
    dp = Dispatcher(storage=storage)

    # Store config on dispatcher so handlers can access it via bot.get("config")
    dp["config"] = config

    # Handlers
    from handlers.admin_commands import router as admin_router
    from handlers.fdr_flow       import router as fdr_router
    from handlers.pm_commands    import router as pm_router
    dp.include_routers(admin_router, pm_router, fdr_router)
    # from handlers.owner_commands import router as owner_router  (future)

    # Make dp.storage available to handlers that need to build FSMContext for other users
    dp["storage"] = dp.storage

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    register_jobs(scheduler, bot, config, dp.storage)
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    try:
        logger.info("Bot polling started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await storage.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
