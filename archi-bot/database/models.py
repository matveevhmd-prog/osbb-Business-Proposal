import aiosqlite

DB_PATH = "archi_bot.db"

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id  INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    role         TEXT    NOT NULL CHECK(role IN ('owner', 'pm', 'executor', 'admin')),
    company_id   INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    code                     TEXT    NOT NULL UNIQUE,
    name                     TEXT    NOT NULL,
    pm_id                    INTEGER NOT NULL REFERENCES users(telegram_id),
    contract_total           REAL    NOT NULL DEFAULT 0,
    planned_hours            REAL    NOT NULL DEFAULT 0,
    planned_margin_pct       REAL    NOT NULL DEFAULT 0,
    planned_completion_date  TEXT,
    status                   TEXT    NOT NULL DEFAULT 'active'
                                     CHECK(status IN ('active', 'paused', 'closed'))
);
"""

CREATE_WEEKLY_FDR = """
CREATE TABLE IF NOT EXISTS weekly_fdr (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id              INTEGER NOT NULL REFERENCES projects(id),
    pm_id                   INTEGER NOT NULL REFERENCES users(telegram_id),
    week_date               TEXT    NOT NULL,  -- ISO date of the Friday
    actual_readiness_pct    REAL,
    planned_readiness_pct   REAL,
    planned_hours_remaining REAL,
    etc_hours               REAL,
    next_act_amount         REAL,
    next_act_date           TEXT,
    planned_margin_pct      REAL,
    forecast_margin_pct     REAL,
    plan_next_week          TEXT,
    comments                TEXT,
    problems                TEXT,
    help_needed             TEXT,
    row_status              TEXT    NOT NULL DEFAULT 'missing'
                                    CHECK(row_status IN ('filled', 'missing', 'skipped')),
    UNIQUE(project_id, week_date)
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(CREATE_USERS)
        await db.execute(CREATE_PROJECTS)
        await db.execute(CREATE_WEEKLY_FDR)
        await db.commit()
