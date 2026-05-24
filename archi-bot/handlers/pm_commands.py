"""PM commands — accessible to PMs (and admin/owner for testing)."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database.queries import (
    get_fdr_for_project_week,
    get_projects_for_pm,
    get_user,
)

logger = logging.getLogger(__name__)
router = Router()

_PM_ROLES = {"pm", "admin", "owner"}


async def _is_pm(message: Message) -> bool:
    user = await get_user(message.from_user.id)
    if user and user.role in _PM_ROLES:
        return True
    await message.answer(
        "⛔ Ця команда доступна тільки PM.\n"
        "Зверніться до адміністратора для отримання доступу."
    )
    return False


def _current_friday() -> str:
    today = date.today()
    return (today - timedelta(days=(today.weekday() - 4) % 7)).isoformat()


# ---------------------------------------------------------------------------
# /fdr — manual survey trigger for this PM
# ---------------------------------------------------------------------------

@router.message(Command("fdr"))
async def cmd_fdr(message: Message, storage) -> None:
    if not await _is_pm(message):
        return

    from handlers.fdr_flow import start_fdr_for_pm
    await start_fdr_for_pm(message.bot, message.from_user.id, storage)


# ---------------------------------------------------------------------------
# /myprojects — list active projects
# ---------------------------------------------------------------------------

@router.message(Command("myprojects"))
async def cmd_myprojects(message: Message) -> None:
    if not await _is_pm(message):
        return

    projects = await get_projects_for_pm(message.from_user.id, status="active")
    if not projects:
        await message.answer("У вас немає активних проектів.")
        return

    lines = [f"📂 <b>Ваші активні проекти ({len(projects)}):</b>\n"]
    for p in projects:
        date_str = f"  До: {p.planned_completion_date}" if p.planned_completion_date else ""
        lines.append(
            f"• <b>{p.code}</b> — {p.name}\n"
            f"  Договір: <b>{p.contract_total:,.0f} грн</b> | "
            f"Год.: <b>{p.planned_hours:.0f}</b> | "
            f"Маржа план: <b>{p.planned_margin_pct:.1f}%</b>"
            f"{date_str}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# /status — this week's FDR fill status per project
# ---------------------------------------------------------------------------

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not await _is_pm(message):
        return

    projects = await get_projects_for_pm(message.from_user.id, status="active")
    if not projects:
        await message.answer("У вас немає активних проектів.")
        return

    week = _current_friday()
    lines = [f"📊 <b>Статус FDR за тиждень {week}:</b>\n"]

    for p in projects:
        fdr = await get_fdr_for_project_week(p.id, week)

        if fdr is None:
            icon, label, detail = "⬜", "не заповнено", ""
        elif fdr.row_status == "filled":
            pct = f" | готовн. {fdr.actual_readiness_pct:.0f}%" if fdr.actual_readiness_pct is not None else ""
            margin = f" | маржа {fdr.forecast_margin_pct:.1f}%" if fdr.forecast_margin_pct is not None else ""
            icon, label, detail = "✅", "заповнено", pct + margin
        elif fdr.row_status == "missing":
            icon, label, detail = "🔴", "пропущено", ""
        else:
            icon, label, detail = "⏭️", fdr.row_status, ""

        lines.append(f"{icon} <b>{p.code}</b> — {p.name}: {label}{detail}")

    lines.append("\nДля заповнення: /fdr")
    await message.answer("\n".join(lines), parse_mode="HTML")
