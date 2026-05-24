"""
FDR (Щотижневий звіт) FSM — Friday PM survey flow.

States per project (looped for each active project of a PM):
  FdrStates.choosing_project   — bot lists projects, PM picks one
  FdrStates.actual_readiness   — "Фактична готовність, %"
  FdrStates.planned_readiness  — "Планова готовність на тиждень, %"
  FdrStates.hours_remaining    — "Планові год. до кінця проекту"
  FdrStates.etc_hours          — "ETC — год. до закриття"
  FdrStates.next_act_amount    — "Сума наступного акту, грн"
  FdrStates.next_act_date      — "Дата підписання акту"
  FdrStates.planned_margin     — "Планова маржа, %"
  FdrStates.forecast_margin    — "Прогнозна маржа, %"
  FdrStates.plan_next_week     — "План на наступний тиждень"
  FdrStates.comments           — "Коментарі"
  FdrStates.problems           — "Проблеми"
  FdrStates.help_needed        — "Потрібна допомога?" (yes/no inline)
  FdrStates.confirm            — show summary, confirm or redo
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database.queries import (
    Project,
    get_fdr_for_project_week,
    get_projects_for_pm,
    get_user,
    upsert_weekly_fdr,
)

logger = logging.getLogger(__name__)
router = Router()


# ---------------------------------------------------------------------------
# FSM state machine
# ---------------------------------------------------------------------------

class FdrStates(StatesGroup):
    choosing_project   = State()
    actual_readiness   = State()
    planned_readiness  = State()
    hours_remaining    = State()
    etc_hours          = State()
    next_act_amount    = State()
    next_act_date      = State()
    planned_margin     = State()
    forecast_margin    = State()
    plan_next_week     = State()
    comments           = State()
    problems           = State()
    help_needed        = State()
    confirm            = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _friday_iso() -> str:
    """Return the ISO date string for the most recent (or current) Friday."""
    today = date.today()
    # weekday(): Mon=0 … Fri=4 … Sun=6
    days_since_friday = (today.weekday() - 4) % 7
    friday = today.replace(day=today.day - days_since_friday)
    # Simple subtraction without timedelta import
    from datetime import timedelta
    friday = today - timedelta(days=days_since_friday)
    return friday.isoformat()


def _projects_keyboard(projects: list[Project]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{p.code} — {p.name}",
            callback_data=f"fdr_proj:{p.id}:{p.code}",
        )]
        for p in projects
    ]
    buttons.append([InlineKeyboardButton(text="✅ Всі заповнені", callback_data="fdr_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="— пропустити —", callback_data="fdr_skip")]
    ])


def _yn_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так", callback_data="fdr_yn:yes"),
            InlineKeyboardButton(text="Ні",  callback_data="fdr_yn:no"),
        ]
    ])


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Зберегти",     callback_data="fdr_save"),
            InlineKeyboardButton(text="🔄 Переробити",   callback_data="fdr_redo"),
        ]
    ])


async def _load_pm_projects(telegram_id: int) -> list[Project]:
    return await get_projects_for_pm(telegram_id, status="active")


def _fmt_optional(val: Optional[object], suffix: str = "") -> str:
    if val is None or val == "":
        return "—"
    return f"{val}{suffix}"


# ---------------------------------------------------------------------------
# Entry point — called by scheduler job fdr_start
# ---------------------------------------------------------------------------

async def start_fdr_for_pm(bot, pm_telegram_id: int, dp_storage) -> None:
    """
    Scheduler calls this for each PM at 16:00 Friday.
    Sends the greeting and first project-selection message.
    """
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.context import FSMContext

    projects = await _load_pm_projects(pm_telegram_id)
    if not projects:
        logger.info("PM %d has no active projects — skipping FDR", pm_telegram_id)
        return

    week = _friday_iso()
    # Filter already fully filled projects
    pending: list[Project] = []
    for p in projects:
        fdr = await get_fdr_for_project_week(p.id, week)
        if fdr is None or fdr.row_status != "filled":
            pending.append(p)

    if not pending:
        await bot.send_message(
            chat_id=pm_telegram_id,
            text="✅ Всі ваші проекти вже заповнені на цей тиждень. Дякую!",
        )
        return

    # Build a temporary FSMContext directly on storage so the bot-side
    # message handlers can continue the conversation
    key = StorageKey(bot_id=bot.id, chat_id=pm_telegram_id, user_id=pm_telegram_id)
    ctx = FSMContext(storage=dp_storage, key=key)

    await ctx.set_state(FdrStates.choosing_project)
    await ctx.update_data(
        week=week,
        pending_ids=[p.id for p in pending],
        current_project_id=None,
        draft={},
    )

    await bot.send_message(
        chat_id=pm_telegram_id,
        text=(
            f"👋 Привіт! П'ятниця — час тижневого звіту.\n\n"
            f"Активні проекти: <b>{len(pending)}</b>\n"
            f"Тиждень: <b>{week}</b>\n\n"
            f"Оберіть проект для заповнення:"
        ),
        parse_mode="HTML",
        reply_markup=_projects_keyboard(pending),
    )


# ---------------------------------------------------------------------------
# Step 1 — choosing_project (callback from inline keyboard)
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(FdrStates.choosing_project), F.data.startswith("fdr_proj:"))
async def cb_choose_project(call: CallbackQuery, state: FSMContext) -> None:
    _, proj_id_str, proj_code = call.data.split(":", 2)
    proj_id = int(proj_id_str)

    data = await state.get_data()
    await state.update_data(current_project_id=proj_id, current_project_code=proj_code, draft={})

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"📋 Проект: <b>{proj_code}</b>\n\n"
        f"<b>Крок 1/11.</b> Фактична готовність проекту, %\n"
        f"(Введіть число від 0 до 100)",
        parse_mode="HTML",
    )
    await state.set_state(FdrStates.actual_readiness)
    await call.answer()


@router.callback_query(StateFilter(FdrStates.choosing_project), F.data == "fdr_done")
async def cb_all_done(call: CallbackQuery, state: FSMContext) -> None:
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("✅ Дякую! Всі звіти прийнято.")
    await state.clear()
    await call.answer()


# ---------------------------------------------------------------------------
# Step 2 — actual_readiness (text message with a percentage)
# ---------------------------------------------------------------------------

@router.message(StateFilter(FdrStates.actual_readiness))
async def msg_actual_readiness(message: Message, state: FSMContext) -> None:
    raw = message.text.strip().replace(",", ".")
    try:
        value = float(raw)
        if not (0 <= value <= 100):
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введіть число від 0 до 100, наприклад: <b>67</b>", parse_mode="HTML")
        return

    data = await state.get_data()
    draft = data.get("draft", {})
    draft["actual_readiness_pct"] = value
    await state.update_data(draft=draft)

    await message.answer(
        f"<b>Крок 2/11.</b> Планова готовність за тижневим планом, %\n"
        f"(Що було заплановано досягти до кінця цього тижня?)",
        parse_mode="HTML",
        reply_markup=_skip_keyboard(),
    )
    await state.set_state(FdrStates.planned_readiness)


# ---------------------------------------------------------------------------
# Skip handler — works from any step that shows a skip button
# ---------------------------------------------------------------------------

_SKIP_STATE_CHAIN: dict[str, tuple[str, State, str]] = {
    # current_state_name: (draft_key, next_state, next_prompt)
    "planned_readiness":  ("planned_readiness_pct",   FdrStates.hours_remaining,  "<b>Крок 3/11.</b> Планові години до кінця проекту\n(Скільки годин залишилось за планом?)"),
    "hours_remaining":    ("planned_hours_remaining",  FdrStates.etc_hours,        "<b>Крок 4/11.</b> ETC — прогнозні години до закриття\n(Ваш поточний прогноз скільки годин потрібно ще?)"),
    "etc_hours":          ("etc_hours",                FdrStates.next_act_amount,  "<b>Крок 5/11.</b> Сума наступного акту, грн\n(0 якщо актів не планується цього тижня)"),
    "next_act_amount":    ("next_act_amount",           FdrStates.next_act_date,    "<b>Крок 6/11.</b> Орієнтовна дата підписання акту\n(формат РРРР-ММ-ДД або «пропустити»)"),
    "next_act_date":      ("next_act_date",             FdrStates.planned_margin,   "<b>Крок 7/11.</b> Планова маржа проекту, %"),
    "planned_margin":     ("planned_margin_pct",        FdrStates.forecast_margin,  "<b>Крок 8/11.</b> Прогнозна маржа, %\n(Ваш поточний прогноз рентабельності)"),
    "forecast_margin":    ("forecast_margin_pct",       FdrStates.plan_next_week,   "<b>Крок 9/11.</b> План на наступний тиждень\n(Що плануєте зробити? Вільний текст)"),
    "plan_next_week":     ("plan_next_week",            FdrStates.comments,         "<b>Крок 10/11.</b> Коментарі (необов'язково)"),
    "comments":           ("comments",                  FdrStates.problems,         "<b>Крок 11/11a.</b> Проблеми (необов'язково)"),
    "problems":           ("problems",                  FdrStates.help_needed,      "<b>Крок 11/11b.</b> Потрібна допомога від керівника?"),
}


@router.callback_query(F.data == "fdr_skip")
async def cb_skip(call: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    state_name = current.split(":")[-1] if current else ""

    if state_name not in _SKIP_STATE_CHAIN:
        await call.answer("Цей крок не можна пропустити.")
        return

    draft_key, next_state, next_prompt = _SKIP_STATE_CHAIN[state_name]
    data = await state.get_data()
    draft = data.get("draft", {})
    draft[draft_key] = None
    await state.update_data(draft=draft)

    await call.message.edit_reply_markup(reply_markup=None)

    if next_state == FdrStates.help_needed:
        await call.message.answer(next_prompt, parse_mode="HTML", reply_markup=_yn_keyboard())
    elif next_state in (FdrStates.plan_next_week, FdrStates.comments, FdrStates.problems):
        await call.message.answer(next_prompt, parse_mode="HTML", reply_markup=_skip_keyboard())
    else:
        await call.message.answer(next_prompt, parse_mode="HTML", reply_markup=_skip_keyboard())

    await state.set_state(next_state)
    await call.answer()
