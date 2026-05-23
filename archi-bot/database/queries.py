from __future__ import annotations

import aiosqlite
from dataclasses import dataclass
from datetime import date
from typing import Optional

from database.models import DB_PATH


# ---------------------------------------------------------------------------
# Dataclasses (lightweight row representations)
# ---------------------------------------------------------------------------

@dataclass
class User:
    telegram_id: int
    name: str
    role: str
    company_id: int = 1


@dataclass
class Project:
    id: int
    code: str
    name: str
    pm_id: int
    contract_total: float
    planned_hours: float
    planned_margin_pct: float
    planned_completion_date: Optional[str]
    status: str


@dataclass
class WeeklyFdr:
    id: int
    project_id: int
    pm_id: int
    week_date: str
    actual_readiness_pct: Optional[float]
    planned_readiness_pct: Optional[float]
    planned_hours_remaining: Optional[float]
    etc_hours: Optional[float]
    next_act_amount: Optional[float]
    next_act_date: Optional[str]
    planned_margin_pct: Optional[float]
    forecast_margin_pct: Optional[float]
    plan_next_week: Optional[str]
    comments: Optional[str]
    problems: Optional[str]
    help_needed: Optional[str]
    row_status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    return aiosqlite.connect(DB_PATH)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def upsert_user(user: User) -> None:
    async with _conn() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT INTO users (telegram_id, name, role, company_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                name       = excluded.name,
                role       = excluded.role,
                company_id = excluded.company_id
            """,
            (user.telegram_id, user.name, user.role, user.company_id),
        )
        await db.commit()


async def get_user(telegram_id: int) -> Optional[User]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return User(**dict(row))


async def get_all_pms() -> list[User]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE role = 'pm'"
        ) as cur:
            rows = await cur.fetchall()
    return [User(**dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

async def insert_project(
    code: str,
    name: str,
    pm_id: int,
    contract_total: float,
    planned_hours: float,
    planned_margin_pct: float,
    planned_completion_date: Optional[str] = None,
    status: str = "active",
) -> int:
    async with _conn() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            INSERT INTO projects
                (code, name, pm_id, contract_total, planned_hours,
                 planned_margin_pct, planned_completion_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (code, name, pm_id, contract_total, planned_hours,
             planned_margin_pct, planned_completion_date, status),
        )
        await db.commit()
        return cur.lastrowid


async def get_project_by_code(code: str) -> Optional[Project]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM projects WHERE code = ?", (code,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return Project(**dict(row))


async def get_projects_for_pm(pm_id: int, status: str = "active") -> list[Project]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM projects WHERE pm_id = ? AND status = ?",
            (pm_id, status),
        ) as cur:
            rows = await cur.fetchall()
    return [Project(**dict(r)) for r in rows]


async def get_all_active_projects() -> list[Project]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM projects WHERE status = 'active'"
        ) as cur:
            rows = await cur.fetchall()
    return [Project(**dict(r)) for r in rows]


async def update_project_field(code: str, field: str, value: object) -> bool:
    allowed = {
        "name", "pm_id", "contract_total", "planned_hours",
        "planned_margin_pct", "planned_completion_date", "status",
    }
    if field not in allowed:
        raise ValueError(f"Field '{field}' is not updatable via this function")
    async with _conn() as db:
        cur = await db.execute(
            f"UPDATE projects SET {field} = ? WHERE code = ?", (value, code)
        )
        await db.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Weekly FDR
# ---------------------------------------------------------------------------

async def upsert_weekly_fdr(
    project_id: int,
    pm_id: int,
    week_date: str,
    **fields,
) -> None:
    columns = [
        "actual_readiness_pct", "planned_readiness_pct", "planned_hours_remaining",
        "etc_hours", "next_act_amount", "next_act_date", "planned_margin_pct",
        "forecast_margin_pct", "plan_next_week", "comments", "problems",
        "help_needed", "row_status",
    ]
    update_pairs = ", ".join(f"{c} = excluded.{c}" for c in columns if c in fields)
    col_names = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))

    async with _conn() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            f"""
            INSERT INTO weekly_fdr (project_id, pm_id, week_date, {col_names})
            VALUES (?, ?, ?, {placeholders})
            ON CONFLICT(project_id, week_date) DO UPDATE SET {update_pairs}
            """,
            (project_id, pm_id, week_date, *fields.values()),
        )
        await db.commit()


async def get_fdr_for_week(week_date: str) -> list[WeeklyFdr]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM weekly_fdr WHERE week_date = ?", (week_date,)
        ) as cur:
            rows = await cur.fetchall()
    return [WeeklyFdr(**dict(r)) for r in rows]


async def get_fdr_for_project_week(
    project_id: int, week_date: str
) -> Optional[WeeklyFdr]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM weekly_fdr WHERE project_id = ? AND week_date = ?",
            (project_id, week_date),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return WeeklyFdr(**dict(row))


async def mark_missing_fdrs(week_date: str, project_ids: list[int]) -> None:
    """Insert row_status='missing' for every project that never started a report."""
    async with _conn() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for pid in project_ids:
            await db.execute(
                """
                INSERT INTO weekly_fdr (project_id, pm_id, week_date, row_status)
                SELECT ?, pm_id, ?, 'missing' FROM projects WHERE id = ?
                ON CONFLICT(project_id, week_date) DO NOTHING
                """,
                (pid, week_date, pid),
            )
        await db.commit()


async def get_latest_fdr_for_project(project_id: int) -> Optional[WeeklyFdr]:
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM weekly_fdr
            WHERE project_id = ?
            ORDER BY week_date DESC
            LIMIT 1
            """,
            (project_id,),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return WeeklyFdr(**dict(row))
