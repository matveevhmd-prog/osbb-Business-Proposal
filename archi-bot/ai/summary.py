from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic
import gspread

from config import Config
from sheets.auth import make_gspread_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ти — COO-аналітик архітектурної компанії. "
    "Генеруй щотижневий summary для власника. "
    "Тільки факти і ризики. Без води."
)

# Fallback column indices (0-based) when header detection fails
_COL_NAME = 1
_COL_CONTRACT = 2
_COL_ACTUAL_HOURS = 3
_COL_PLANNED_HOURS = 4
_COL_COMPLETION_PCT = 5
_COL_ETC_HOURS = 6
_COL_ACTS_SIGNED = 7
_COL_CURRENT_COST = 8
_COL_PROJECTED_MARGIN = 9


@dataclass
class ProjectMetrics:
    name: str
    contract_total: float
    actual_hours: float
    planned_hours: float
    completion_pct: float
    etc_hours: float
    acts_signed: float
    current_cost: float
    projected_margin_pct: float
    hours_utilization_pct: float
    margin_risk: bool      # projected_margin_pct < 25
    etc_overrun: bool      # actual_hours > planned_hours * (completion_pct / 100)


def _safe_float(val: object) -> float:
    if val is None:
        return 0.0
    s = str(val).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _detect_column_indices(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    keywords = {
        "name":             ["назва", "проект", "name"],
        "contract":         ["договір", "контракт", "contract", "сума"],
        "actual_hours":     ["факт", "actual", "відпрацьовано"],
        "planned_hours":    ["план", "planned", "заплановано"],
        "completion_pct":   ["готовн", "completion", "%готов"],
        "etc_hours":        ["etc", "залишок годин", "remaining"],
        "acts_signed":      ["акт", "підписано", "acts"],
        "current_cost":     ["собівартість", "витрати", "cost"],
        "projected_margin": ["рентабельн", "маржа", "margin", "profitab"],
    }
    lower_headers = [h.lower() for h in headers]
    for field, kws in keywords.items():
        for i, h in enumerate(lower_headers):
            if any(kw in h for kw in kws):
                mapping[field] = i
                break
    return mapping


def _parse_projects(worksheet: gspread.Worksheet) -> list[ProjectMetrics]:
    all_values = worksheet.get_all_values()
    if not all_values:
        return []

    # Find header row — first row that has more than 3 non-empty cells
    header_row_idx = 0
    for i, row in enumerate(all_values):
        non_empty = sum(1 for c in row if str(c).strip())
        if non_empty >= 4:
            header_row_idx = i
            break

    headers = all_values[header_row_idx]
    col = _detect_column_indices(headers)

    def _get(row: list, field: str, fallback: int) -> object:
        idx = col.get(field, fallback)
        return row[idx] if idx < len(row) else ""

    projects: list[ProjectMetrics] = []
    for row in all_values[header_row_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        name = str(_get(row, "name", _COL_NAME)).strip()
        if not name:
            continue

        contract_total   = _safe_float(_get(row, "contract",         _COL_CONTRACT))
        actual_hours     = _safe_float(_get(row, "actual_hours",     _COL_ACTUAL_HOURS))
        planned_hours    = _safe_float(_get(row, "planned_hours",    _COL_PLANNED_HOURS))
        completion_pct   = _safe_float(_get(row, "completion_pct",   _COL_COMPLETION_PCT))
        etc_hours        = _safe_float(_get(row, "etc_hours",        _COL_ETC_HOURS))
        acts_signed      = _safe_float(_get(row, "acts_signed",      _COL_ACTS_SIGNED))
        current_cost     = _safe_float(_get(row, "current_cost",     _COL_CURRENT_COST))
        projected_margin = _safe_float(_get(row, "projected_margin", _COL_PROJECTED_MARGIN))

        hours_utilization_pct = (
            (actual_hours / planned_hours * 100) if planned_hours > 0 else 0.0
        )
        margin_risk = projected_margin < 25.0
        # ETC overrun: more hours spent than plan allows for completion so far
        expected_hours_at_completion = planned_hours * (completion_pct / 100) if completion_pct > 0 else 0.0
        etc_overrun = actual_hours > expected_hours_at_completion if expected_hours_at_completion > 0 else False

        projects.append(ProjectMetrics(
            name=name,
            contract_total=contract_total,
            actual_hours=actual_hours,
            planned_hours=planned_hours,
            completion_pct=completion_pct,
            etc_hours=etc_hours,
            acts_signed=acts_signed,
            current_cost=current_cost,
            projected_margin_pct=projected_margin,
            hours_utilization_pct=hours_utilization_pct,
            margin_risk=margin_risk,
            etc_overrun=etc_overrun,
        ))

    # Top 10 by contract total, descending
    projects.sort(key=lambda p: p.contract_total, reverse=True)
    return projects[:10]


def _build_prompt(projects: list[ProjectMetrics]) -> str:
    lines = ["Дані по топ-10 проектам портфеля:\n"]
    for i, p in enumerate(projects, 1):
        status = "🔴" if (p.margin_risk and p.etc_overrun) else ("🟡" if (p.margin_risk or p.etc_overrun) else "🟢")
        flags = []
        if p.margin_risk:
            flags.append(f"маржа {p.projected_margin_pct:.1f}%<25%")
        if p.etc_overrun:
            flags.append(f"годин факт {p.actual_hours:.0f} > план×{p.completion_pct:.0f}%")
        flag_str = f" ⚠️ {', '.join(flags)}" if flags else ""
        lines.append(
            f"{i}. {status} {p.name} | договір {p.contract_total:,.0f} грн | "
            f"готовність {p.completion_pct:.0f}% | "
            f"маржа {p.projected_margin_pct:.1f}%{flag_str}"
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


def _fetch_projects_sync(config: Config) -> list[ProjectMetrics]:
    client = make_gspread_client(config)
    spreadsheet = client.open_by_key(config.abmk_file_id)
    worksheet = spreadsheet.get_worksheet(0)
    return _parse_projects(worksheet)


async def generate_summary(config: Config) -> str:
    try:
        projects = await asyncio.to_thread(_fetch_projects_sync, config)
    except Exception as exc:
        logger.exception("Failed to read portfolio sheet")
        return f"⚠️ Не вдалося прочитати файл ABMK: {exc}"

    if not projects:
        return "⚠️ Портфель порожній або файл не містить даних."

    prompt = _build_prompt(projects)

    try:
        ai_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        response = await asyncio.to_thread(
            lambda: ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = response.content[0].text.strip()
        # Enforce 800-char limit hard
        if len(text) > 800:
            text = text[:797] + "…"
        return text
    except Exception as exc:
        logger.exception("Claude API call failed")
        return f"⚠️ Помилка Claude API: {exc}"
