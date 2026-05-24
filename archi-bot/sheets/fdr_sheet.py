from __future__ import annotations

import asyncio
import logging

import gspread

from config import Config
from database.queries import Project, WeeklyFdr
from sheets.auth import make_gspread_client

logger = logging.getLogger(__name__)

_HEADERS = [
    "Тиждень", "Код проекту", "Назва проекту", "PM",
    "Факт. готовн. %", "Планова готовн. %",
    "Планові год. до кінця", "ETC год.",
    "Наст. акт (грн)", "Дата акту",
    "Планова маржа %", "Прогн. маржа %",
    "План наст. тиждень", "Коментарі", "Проблеми", "Допомога", "Статус",
]


def _opt(val: object) -> object:
    return "" if val is None else val


def _row_values(project: Project, fdr: WeeklyFdr, pm_name: str) -> list:
    return [
        fdr.week_date,
        project.code,
        project.name,
        pm_name,
        _opt(fdr.actual_readiness_pct),
        _opt(fdr.planned_readiness_pct),
        _opt(fdr.planned_hours_remaining),
        _opt(fdr.etc_hours),
        _opt(fdr.next_act_amount),
        _opt(fdr.next_act_date),
        _opt(fdr.planned_margin_pct),
        _opt(fdr.forecast_margin_pct),
        _opt(fdr.plan_next_week),
        _opt(fdr.comments),
        _opt(fdr.problems),
        _opt(fdr.help_needed),
        fdr.row_status,
    ]


async def write_fdr_row(
    config: Config,
    project: Project,
    fdr: WeeklyFdr,
    pm_name: str,
) -> None:
    """Upsert one FDR row into the week's tab of the FDR Google Sheet."""

    def _sync() -> None:
        client = make_gspread_client(config, readonly=False)
        ss = client.open_by_key(config.google_fdr_sheet_id)

        try:
            ws = ss.worksheet(fdr.week_date)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(title=fdr.week_date, rows=500, cols=len(_HEADERS))
            ws.append_row(_HEADERS, value_input_option="USER_ENTERED")

        row_data = _row_values(project, fdr, pm_name)
        all_values = ws.get_all_values()

        # Update in place if the project code is already in this week's tab
        for i, row in enumerate(all_values):
            if len(row) > 1 and row[1] == project.code:
                ws.update(f"A{i + 1}", [row_data], value_input_option="USER_ENTERED")
                logger.info("Updated FDR row %s / %s", project.code, fdr.week_date)
                return

        ws.append_row(row_data, value_input_option="USER_ENTERED")
        logger.info("Appended FDR row %s / %s", project.code, fdr.week_date)

    await asyncio.to_thread(_sync)
