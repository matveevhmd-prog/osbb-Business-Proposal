-- Run this once in the Supabase SQL Editor before starting the bot.
-- Project Settings → SQL Editor → New query → paste → Run

CREATE TABLE IF NOT EXISTS users (
    telegram_id  BIGINT  PRIMARY KEY,
    name         TEXT    NOT NULL,
    role         TEXT    NOT NULL CHECK(role IN ('owner','pm','executor','admin')),
    company_id   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS projects (
    id                       SERIAL  PRIMARY KEY,
    code                     TEXT    NOT NULL UNIQUE,
    name                     TEXT    NOT NULL,
    pm_id                    BIGINT  NOT NULL REFERENCES users(telegram_id),
    contract_total           REAL    NOT NULL DEFAULT 0,
    planned_hours            REAL    NOT NULL DEFAULT 0,
    planned_margin_pct       REAL    NOT NULL DEFAULT 0,
    planned_completion_date  TEXT,
    status                   TEXT    NOT NULL DEFAULT 'active'
                                     CHECK(status IN ('active','paused','closed'))
);

CREATE TABLE IF NOT EXISTS weekly_fdr (
    id                      SERIAL  PRIMARY KEY,
    project_id              INTEGER NOT NULL REFERENCES projects(id),
    pm_id                   BIGINT  NOT NULL REFERENCES users(telegram_id),
    week_date               TEXT    NOT NULL,
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
                                    CHECK(row_status IN ('filled','missing','skipped')),
    UNIQUE(project_id, week_date)
);

CREATE TABLE IF NOT EXISTS fsm_storage (
    bot_id   BIGINT NOT NULL,
    chat_id  BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    destiny  TEXT   NOT NULL,
    state    TEXT,
    data     JSONB  NOT NULL DEFAULT '{}',
    PRIMARY KEY (bot_id, chat_id, user_id, destiny)
);

-- Disable RLS on all tables so the service_role key has full access.
ALTER TABLE users        DISABLE ROW LEVEL SECURITY;
ALTER TABLE projects     DISABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_fdr   DISABLE ROW LEVEL SECURITY;
ALTER TABLE fsm_storage  DISABLE ROW LEVEL SECURITY;
