"""AI weekly summary — data sourced from SQLite, no Google dependency."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic

from config import Config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ти — COO-аналітик архітектурної компанії. "
    "Генеруй щотижневий summary для власника. "
    "Тільки факти і ризики. Без води."
)


@dataclass
class ProjectMetrics:
    name: str
    code: str
    contract_total: float
    planned_margin_pct: float
    actual_readiness_pct: Optional[float]
    planned_readiness_pct: Optional[float]
    etc_hours: Optional[float]
    forecast_margin_pct: Optional[float]
    problems: Optional[str]
    help_needed: Optional[str]
    margin_risk: bool    # forecast (or plan) margin < 25 %
    schedule_risk: bool  # actual readiness > 10 pp behind plan


async def _fetch_projects() -> list[ProjectMetrics]:
    from database.queries import (
        get_all_active_projects,
        get_latest_fdr_for_project,
    )

    projects = await get_all_active_projects()
    result: list[ProjectMetrics] = []

    for p in projects:
        fdr = await get_latest_fdr_for_project(p.id)

        actual_ready   = fdr.actual_readiness_pct  if fdr else None
        planned_ready  = fdr.planned_readiness_pct if fdr else None
        etc            = fdr.etc_hours             if fdr else None
        forecast_m     = fdr.forecast_margin_pct   if fdr else None
        problems       = fdr.problems              if fdr else None
        help_needed    = fdr.help_needed           if fdr else None

        margin_risk = (
            (forecast_m is not None and forecast_m < 25.0)
            or p.planned_margin_pct < 25.0
        )
        schedule_risk = (
            actual_ready is not None
            and planned_ready is not None
            and actual_ready < planned_ready - 10.0
        )

        result.append(ProjectMetrics(
            name=p.name,
            code=p.code,
            contract_total=p.contract_total,
            planned_margin_pct=p.planned_margin_pct,
            actual_readiness_pct=actual_ready,
            planned_readiness_pct=planned_ready,
            etc_hours=etc,
            forecast_margin_pct=forecast_m,
            problems=problems,
            help_needed=help_needed,
            margin_risk=margin_risk,
            schedule_risk=schedule_risk,
        ))

    result.sort(key=lambda p: p.contract_total, reverse=True)
    return result[:10]


def _build_prompt(projects: list[ProjectMetrics]) -> str:
    lines = ["Дані по топ-10 проектам портфеля:\n"]
    for i, p in enumerate(projects, 1):
        both = p.margin_risk and p.schedule_risk
        either = p.margin_risk or p.schedule_risk
        status = "🔴" if both else ("🟡" if either else "🟢")

        flags: list[str] = []
        if p.margin_risk:
            m = p.forecast_margin_pct if p.forecast_margin_pct is not None else p.planned_margin_pct
            flags.append(f"маржа {m:.1f}%<25%")
        if p.schedule_risk:
            flags.append(
                f"відстає: факт {p.actual_readiness_pct:.0f}%"
                f" < план {p.planned_readiness_pct:.0f}%"
            )
        if p.help_needed == "yes":
            flags.append("🆘 потрібна допомога")
        if p.problems:
            flags.append(f"проблема: {p.problems[:60]}")

        flag_str = f" ⚠️ {', '.join(flags)}" if flags else ""
        ready = f"{p.actual_readiness_pct:.0f}%" if p.actual_readiness_pct is not None else "?"
        margin = (
            f" | маржа прогн. {p.forecast_margin_pct:.1f}%"
            if p.forecast_margin_pct is not None
            else f" | маржа план {p.planned_margin_pct:.1f}%"
        )
        lines.append(
            f"{i}. {status} {p.code} — {p.name} | "
            f"договір {p.contract_total:,.0f} грн | "
            f"готовн. {ready}{margin}{flag_str}"
        )

    lines.append(
        "\nСформуй:\n"
        "1. Оцінка здоров'я портфеля (1 рядок)\n"
        "2. Топ-3 ризики (з назвами проектів)\n"
        "3. 2-3 рекомендовані дії\n"
        "Відповідь у форматі Telegram HTML: <b>розділ</b>, ⚠️ для ризиків, ✅ для дій. "
        "Максимум 800 символів. Тільки Ukrainian."
    )
    return "\n".join(lines)


async def generate_summary(config: Config) -> str:
    try:
        projects = await _fetch_projects()
    except Exception as exc:
        logger.exception("Failed to load portfolio from DB")
        return f"⚠️ Не вдалося прочитати дані: {exc}"

    if not projects:
        return "⚠️ Немає активних проектів у базі даних."

    prompt = _build_prompt(projects)

    try:
        ai_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        response = await asyncio.to_thread(
            lambda: ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                system=[{
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = response.content[0].text.strip()
        if len(text) > 800:
            text = text[:797] + "…"
        return text
    except Exception as exc:
        logger.exception("Claude API call failed")
        return f"⚠️ Помилка Claude API: {exc}"
