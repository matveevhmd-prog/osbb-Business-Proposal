from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from database.models import get_client


# ---------------------------------------------------------------------------
# Dataclasses
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
# Users
# ---------------------------------------------------------------------------

async def upsert_user(user: User) -> None:
    sb = get_client()
    await sb.table("users").upsert({
        "telegram_id": user.telegram_id,
        "name": user.name,
        "role": user.role,
        "company_id": user.company_id,
    }).execute()


async def get_user(telegram_id: int) -> Optional[User]:
    sb = get_client()
    resp = await sb.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if not resp.data:
        return None
    return User(**resp.data[0])


async def get_all_pms() -> list[User]:
    sb = get_client()
    resp = await sb.table("users").select("*").eq("role", "pm").execute()
    return [User(**r) for r in resp.data]


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
    sb = get_client()
    resp = await sb.table("projects").insert({
        "code": code,
        "name": name,
        "pm_id": pm_id,
        "contract_total": contract_total,
        "planned_hours": planned_hours,
        "planned_margin_pct": planned_margin_pct,
        "planned_completion_date": planned_completion_date,
        "status": status,
    }).execute()
    return resp.data[0]["id"]


async def get_project_by_code(code: str) -> Optional[Project]:
    sb = get_client()
    resp = await sb.table("projects").select("*").eq("code", code).execute()
    if not resp.data:
        return None
    return Project(**resp.data[0])


async def get_projects_for_pm(pm_id: int, status: str = "active") -> list[Project]:
    sb = get_client()
    resp = (
        await sb.table("projects")
        .select("*")
        .eq("pm_id", pm_id)
        .eq("status", status)
        .execute()
    )
    return [Project(**r) for r in resp.data]


async def get_all_active_projects() -> list[Project]:
    sb = get_client()
    resp = await sb.table("projects").select("*").eq("status", "active").execute()
    return [Project(**r) for r in resp.data]


async def update_project_field(code: str, field: str, value: object) -> bool:
    allowed = {
        "name", "pm_id", "contract_total", "planned_hours",
        "planned_margin_pct", "planned_completion_date", "status",
    }
    if field not in allowed:
        raise ValueError(f"Field '{field}' is not updatable via this function")
    sb = get_client()
    resp = await sb.table("projects").update({field: value}).eq("code", code).execute()
    return len(resp.data) > 0


# ---------------------------------------------------------------------------
# Weekly FDR
# ---------------------------------------------------------------------------

async def upsert_weekly_fdr(
    project_id: int,
    pm_id: int,
    week_date: str,
    **fields,
) -> None:
    sb = get_client()
    await sb.table("weekly_fdr").upsert(
        {"project_id": project_id, "pm_id": pm_id, "week_date": week_date, **fields},
        on_conflict="project_id,week_date",
    ).execute()


async def get_fdr_for_week(week_date: str) -> list[WeeklyFdr]:
    sb = get_client()
    resp = await sb.table("weekly_fdr").select("*").eq("week_date", week_date).execute()
    return [WeeklyFdr(**r) for r in resp.data]


async def get_fdr_for_project_week(
    project_id: int, week_date: str
) -> Optional[WeeklyFdr]:
    sb = get_client()
    resp = (
        await sb.table("weekly_fdr")
        .select("*")
        .eq("project_id", project_id)
        .eq("week_date", week_date)
        .execute()
    )
    if not resp.data:
        return None
    return WeeklyFdr(**resp.data[0])


async def mark_missing_fdrs(week_date: str, project_ids: list[int]) -> None:
    """Insert row_status='missing' for every project that never started a report."""
    sb = get_client()
    for pid in project_ids:
        proj_resp = await sb.table("projects").select("pm_id").eq("id", pid).execute()
        if not proj_resp.data:
            continue
        pm_id = proj_resp.data[0]["pm_id"]
        await sb.table("weekly_fdr").upsert(
            {"project_id": pid, "pm_id": pm_id, "week_date": week_date, "row_status": "missing"},
            on_conflict="project_id,week_date",
            ignore_duplicates=True,
        ).execute()


async def get_latest_fdr_for_project(project_id: int) -> Optional[WeeklyFdr]:
    sb = get_client()
    resp = (
        await sb.table("weekly_fdr")
        .select("*")
        .eq("project_id", project_id)
        .order("week_date", desc=True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    return WeeklyFdr(**resp.data[0])
