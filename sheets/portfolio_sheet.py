"""CSV export for the portfolio snapshot — reads directly from SQLite."""
from __future__ import annotations

import csv
import io
from datetime import date

from database.queries import (
    get_all_active_projects,
    get_latest_fdr_for_project,
    get_user,
)

_HEADERS = [
    "Код", "Назва проекту", "PM",
    "Договір (грн)", "Год. план", "Маржа план %",
    "Дата завершення", "Стан",
    "Останній тиждень", "Факт. готовн. %",
    "ETC год.", "Прогн. маржа %",
    "Проблеми", "Допомога потрібна",
]


def _opt(val: object) -> str:
    return "" if val is None else str(val)


async def export_portfolio_csv() -> tuple[str, bytes]:
    """
    One row per active project, filled with the latest weekly FDR data.
    Returns (filename, utf-8-sig bytes).
    """
    projects = await get_all_active_projects()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_HEADERS)

    for p in projects:
        fdr = await get_latest_fdr_for_project(p.id)
        pm = await get_user(p.pm_id)
        pm_name = pm.name if pm else str(p.pm_id)

        writer.writerow([
            p.code,
            p.name,
            pm_name,
            p.contract_total,
            p.planned_hours,
            p.planned_margin_pct,
            _opt(p.planned_completion_date),
            p.status,
            fdr.week_date if fdr else "",
            _opt(fdr.actual_readiness_pct if fdr else None),
            _opt(fdr.etc_hours if fdr else None),
            _opt(fdr.forecast_margin_pct if fdr else None),
            _opt(fdr.problems if fdr else None),
            _opt(fdr.help_needed if fdr else None),
        ])

    filename = f"portfolio_{date.today().isoformat()}.csv"
    return filename, buf.getvalue().encode("utf-8-sig")
