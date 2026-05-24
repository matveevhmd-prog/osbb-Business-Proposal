"""CSV export for weekly FDR records — reads directly from SQLite."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import Optional

from database.queries import (
    get_all_active_projects,
    get_fdr_for_week,
    get_user,
)

_HEADERS = [
    "Тиждень", "Код проекту", "Назва проекту", "PM",
    "Факт. готовн. %", "Планова готовн. %",
    "Планові год. до кінця", "ETC год.",
    "Наст. акт (грн)", "Дата акту",
    "Планова маржа %", "Прогн. маржа %",
    "План наст. тиждень", "Коментарі", "Проблеми", "Допомога", "Статус",
]


def _opt(val: object) -> str:
    return "" if val is None else str(val)


def _current_friday() -> str:
    today = date.today()
    return (today - timedelta(days=(today.weekday() - 4) % 7)).isoformat()


async def export_fdr_csv(week_date: Optional[str] = None) -> tuple[str, bytes]:
    """
    Generate a CSV for one week's FDR records.
    Defaults to the most recent Friday if week_date is omitted.
    Returns (filename, utf-8-sig bytes).
    """
    if week_date is None:
        week_date = _current_friday()

    records = await get_fdr_for_week(week_date)

    # Build project lookup once
    all_projects = await get_all_active_projects()
    proj_map = {p.id: p for p in all_projects}

    pm_cache: dict[int, str] = {}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_HEADERS)

    for fdr in records:
        project = proj_map.get(fdr.project_id)
        if fdr.pm_id not in pm_cache:
            pm = await get_user(fdr.pm_id)
            pm_cache[fdr.pm_id] = pm.name if pm else str(fdr.pm_id)

        writer.writerow([
            fdr.week_date,
            project.code if project else str(fdr.project_id),
            project.name if project else "",
            pm_cache[fdr.pm_id],
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
        ])

    filename = f"fdr_{week_date}.csv"
    # utf-8-sig so Excel opens Cyrillic correctly without a BOM dialog
    return filename, buf.getvalue().encode("utf-8-sig")
