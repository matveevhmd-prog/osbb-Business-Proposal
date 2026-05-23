from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Config


def register_jobs(scheduler: AsyncIOScheduler, bot, config: Config) -> None:
    """
    Schedule:
      Friday  16:00 — start FDR survey for all PMs
      Friday  18:00 — reminder to non-responders
      Friday  20:00 — final reminder + mark missing
      Saturday 08:00 — update portfolio map sheet
      Monday  09:00 — AI summary + weekly meeting reminder to owner
    """
    # Placeholders — replaced when handlers/sheets/ai modules are built
    async def _noop(label: str):
        import logging
        logging.getLogger(__name__).info("Scheduler fired: %s", label)

    scheduler.add_job(
        lambda: _noop("fdr_start"),
        CronTrigger(day_of_week="fri", hour=16, minute=0),
        id="fdr_start",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _noop("fdr_reminder_1"),
        CronTrigger(day_of_week="fri", hour=18, minute=0),
        id="fdr_reminder_1",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _noop("fdr_final"),
        CronTrigger(day_of_week="fri", hour=20, minute=0),
        id="fdr_final",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _noop("portfolio_update"),
        CronTrigger(day_of_week="sat", hour=8, minute=0),
        id="portfolio_update",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _noop("weekly_summary"),
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_summary",
        replace_existing=True,
    )
