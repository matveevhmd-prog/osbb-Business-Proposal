import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import load_config
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

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Store config on dispatcher so handlers can access it via bot.get("config")
    dp["config"] = config

    # Handlers (registered here once each module is built)
    # from handlers.admin_commands import router as admin_router
    # from handlers.owner_commands import router as owner_router
    # from handlers.pm_commands   import router as pm_router
    # from handlers.fdr_flow      import router as fdr_router
    # dp.include_routers(admin_router, owner_router, pm_router, fdr_router)

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    register_jobs(scheduler, bot, config)
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    try:
        logger.info("Bot polling started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
