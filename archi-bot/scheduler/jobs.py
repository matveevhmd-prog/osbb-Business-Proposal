from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Config

logger = logging.getLogger(__name__)


def _this_friday() -> str:
    today = date.today()
    return (today - timedelta(days=(today.weekday() - 4) % 7)).isoformat()


def register_jobs(
    scheduler: AsyncIOScheduler,
    bot,
    config: Config,
    storage,
) -> None:
    """
    Friday 16:00 — FDR survey starts for all PMs
    Friday 18:00 — reminder to non-responders
    Friday 20:00 — final reminder + mark missing rows
    Saturday 08:00 — rebuild portfolio map sheet
    Monday  09:00 — AI summary → owner
    """

    # ------------------------------------------------------------------
    # Friday 16:00 — start FDR for every active PM
    # ------------------------------------------------------------------
    async def _fdr_start() -> None:
        from database.queries import get_all_pms
        from handlers.fdr_flow import start_fdr_for_pm

        logger.info("Scheduler fired: fdr_start")
        pms = await get_all_pms()
        for pm in pms:
            try:
                await start_fdr_for_pm(bot, pm.telegram_id, storage)
            except Exception as exc:
                logger.error("fdr_start PM %d: %s", pm.telegram_id, exc)
        logger.info("fdr_start: launched for %d PMs", len(pms))

    # ------------------------------------------------------------------
    # Friday 18:00 — nudge PMs who haven't filled yet
    # ------------------------------------------------------------------
    async def _fdr_reminder_1() -> None:
        from database.queries import (
            get_all_pms,
            get_fdr_for_project_week,
            get_projects_for_pm,
        )

        logger.info("Scheduler fired: fdr_reminder_1")
        week = _this_friday()
        pms = await get_all_pms()

        for pm in pms:
            projects = await get_projects_for_pm(pm.telegram_id, status="active")
            pending = [
                p.code for p in projects
                if (await get_fdr_for_project_week(p.id, week)) is None
                or (await get_fdr_for_project_week(p.id, week)).row_status != "filled"
            ]
            if not pending:
                continue
            try:
                await bot.send_message(
                    chat_id=pm.telegram_id,
                    text=(
                        "⏰ <b>Нагадування!</b> Незаповнені звіти:\n"
                        + "".join(f"• <b>{c}</b>\n" for c in pending)
                        + "\nВикористайте /fdr для заповнення."
                    ),
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.warning("fdr_reminder_1 PM %d: %s", pm.telegram_id, exc)

    # ------------------------------------------------------------------
    # Friday 20:00 — mark remaining as 'missing', notify owner
    # ------------------------------------------------------------------
    async def _fdr_final() -> None:
        from database.queries import (
            get_all_pms,
            get_fdr_for_project_week,
            get_projects_for_pm,
            mark_missing_fdrs,
        )

        logger.info("Scheduler fired: fdr_final")
        week = _this_friday()
        pms = await get_all_pms()
        missing_report: list[tuple[str, list[str]]] = []

        for pm in pms:
            projects = await get_projects_for_pm(pm.telegram_id, status="active")
            miss_ids, miss_codes = [], []
            for p in projects:
                fdr = await get_fdr_for_project_week(p.id, week)
                if fdr is None or fdr.row_status != "filled":
                    miss_ids.append(p.id)
                    miss_codes.append(p.code)

            if miss_ids:
                await mark_missing_fdrs(week, miss_ids)
                missing_report.append((pm.name, miss_codes))
                try:
                    await bot.send_message(
                        chat_id=pm.telegram_id,
                        text=(
                            "🔴 Дедлайн минув. Незаповнені звіти марковані як <i>пропущено</i>:\n"
                            + "".join(f"• <b>{c}</b>\n" for c in miss_codes)
                        ),
                        parse_mode="HTML",
                    )
                except Exception as exc:
                    logger.warning("fdr_final PM %d: %s", pm.telegram_id, exc)

        if missing_report:
            lines = [f"📋 <b>Пропущені FDR (тиждень {week}):</b>\n"]
            for name, codes in missing_report:
                lines.append(f"• {name}: " + ", ".join(codes))
            try:
                await bot.send_message(
                    chat_id=config.owner_telegram_id,
                    text="\n".join(lines),
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.warning("fdr_final owner notify: %s", exc)

        logger.info(
            "fdr_final done. Missing: %d PMs",
            len(missing_report),
        )

    # ------------------------------------------------------------------
    # Saturday 08:00 — rebuild portfolio map
    # ------------------------------------------------------------------
    async def _portfolio_update() -> None:
        from sheets.portfolio_sheet import update_portfolio_map

        logger.info("Scheduler fired: portfolio_update")
        await update_portfolio_map(config)
        logger.info("Portfolio map updated")

    # ------------------------------------------------------------------
    # Monday 09:00 — AI summary → owner
    # ------------------------------------------------------------------
    async def _weekly_summary() -> None:
        from ai.summary import generate_summary

        logger.info("Scheduler fired: weekly_summary")
        text = await generate_summary(config)
        await bot.send_message(
            chat_id=config.owner_telegram_id,
            text=text,
            parse_mode="HTML",
        )
        logger.info("Weekly summary sent to owner %d", config.owner_telegram_id)

    # ------------------------------------------------------------------
    # Register all jobs
    # ------------------------------------------------------------------
    scheduler.add_job(
        _fdr_start,
        CronTrigger(day_of_week="fri", hour=16, minute=0),
        id="fdr_start",
        replace_existing=True,
    )
    scheduler.add_job(
        _fdr_reminder_1,
        CronTrigger(day_of_week="fri", hour=18, minute=0),
        id="fdr_reminder_1",
        replace_existing=True,
    )
    scheduler.add_job(
        _fdr_final,
        CronTrigger(day_of_week="fri", hour=20, minute=0),
        id="fdr_final",
        replace_existing=True,
    )
    scheduler.add_job(
        _portfolio_update,
        CronTrigger(day_of_week="sat", hour=8, minute=0),
        id="portfolio_update",
        replace_existing=True,
    )
    scheduler.add_job(
        _weekly_summary,
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_summary",
        replace_existing=True,
    )
