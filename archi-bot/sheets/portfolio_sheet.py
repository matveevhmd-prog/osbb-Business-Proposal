from __future__ import annotations

import asyncio
import logging
from typing import Optional

import gspread

from config import Config
from database.queries import (
    Project,
    WeeklyFdr,
    get_all_active_projects,
    get_latest_fdr_for_project,
    get_user,
)
from sheets.auth import make_gspread_client

logger = logging.getLogger(__name__)

_PORTFOLIO_TAB = "Карта портфеля"

_HEADERS = [
    "Код", "Назва проекту", "PM",
    "Договір (грн)", "Стан",
    "Останній тиждень", "Факт. готовн. %",
    "ETC год.", "Прогн. маржа %",
    "Проблеми", "Допомога потрібна",
]


def _opt(val: object) -> object:
    return "" if val is None else val


def _project_row(
    project: Project,
    pm_name: str,
    fdr: Optional[WeeklyFdr],
) -> list:
    return [
        project.code,
        project.name,
        pm_name,
        project.contract_total,
        project.status,
        fdr.week_date if fdr else "",
        _opt(fdr.actual_readiness_pct if fdr else None),
        _opt(fdr.etc_hours if fdr else None),
        _opt(fdr.forecast_margin_pct if fdr else None),
        _opt(fdr.problems if fdr else None),
        _opt(fdr.help_needed if fdr else None),
    ]


async def update_portfolio_map(config: Config) -> None:
    """Rebuild the portfolio-map tab: one row per active project, latest FDR data."""
    projects = await get_all_active_projects()

    rows: list[tuple[str, list]] = []
    for project in projects:
        fdr = await get_latest_fdr_for_project(project.id)
        pm = await get_user(project.pm_id)
        pm_name = pm.name if pm else str(project.pm_id)
        rows.append((project.code, _project_row(project, pm_name, fdr)))

    def _sync() -> None:
        client = make_gspread_client(config, readonly=False)
        ss = client.open_by_key(config.google_portfolio_sheet_id)

        try:
            ws = ss.worksheet(_PORTFOLIO_TAB)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(
                title=_PORTFOLIO_TAB,
                rows=200,
                cols=len(_HEADERS),
            )
            ws.append_row(_HEADERS, value_input_option="USER_ENTERED")

        all_values = ws.get_all_values()

        # Re-seed header if the sheet was cleared externally
        if not all_values or all_values[0][0] != "Код":
            ws.clear()
            ws.append_row(_HEADERS, value_input_option="USER_ENTERED")
            all_values = [_HEADERS]

        # Build code → 1-based row-number index (skip header at idx 0)
        existing: dict[str, int] = {
            row[0]: idx + 1
            for idx, row in enumerate(all_values)
            if idx > 0 and row and row[0]
        }

        for code, row_data in rows:
            if code in existing:
                ws.update(
                    f"A{existing[code]}",
                    [row_data],
                    value_input_option="USER_ENTERED",
                )
            else:
                ws.append_row(row_data, value_input_option="USER_ENTERED")

        logger.info("Portfolio map updated: %d projects", len(rows))

    await asyncio.to_thread(_sync)
