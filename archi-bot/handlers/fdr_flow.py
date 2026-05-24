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


# ---------------------------------------------------------------------------
# Generic step helpers
# ---------------------------------------------------------------------------

def _fmt(val: object, suffix: str = "", money: bool = False) -> str:
    if val is None or val == "":
        return "—"
    if isinstance(val, (int, float)):
        n = float(val)
        if money:
            return f"{n:,.0f}{suffix}".replace(",", " ")
        return f"{int(n)}{suffix}" if n == int(n) else f"{n:.1f}{suffix}"
    return f"{val}{suffix}"


async def _advance_to(
    answer_fn,
    state: FSMContext,
    next_state: State,
    prompt: str,
) -> None:
    await state.set_state(next_state)
    if next_state == FdrStates.help_needed:
        await answer_fn(prompt, parse_mode="HTML", reply_markup=_yn_keyboard())
    else:
        await answer_fn(prompt, parse_mode="HTML", reply_markup=_skip_keyboard())


async def _handle_float_step(
    message: Message, state: FSMContext, state_name: str
) -> None:
    raw = message.text.strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        await message.answer(
            "⚠️ Введіть число, наприклад: <b>42.5</b>", parse_mode="HTML"
        )
        return
    draft_key, next_state, next_prompt = _SKIP_STATE_CHAIN[state_name]
    data = await state.get_data()
    draft = data.get("draft", {})
    draft[draft_key] = value
    await state.update_data(draft=draft)
    await _advance_to(message.answer, state, next_state, next_prompt)


async def _handle_text_step(
    message: Message, state: FSMContext, state_name: str
) -> None:
    value = message.text.strip() or None
    draft_key, next_state, next_prompt = _SKIP_STATE_CHAIN[state_name]
    data = await state.get_data()
    draft = data.get("draft", {})
    draft[draft_key] = value
    await state.update_data(draft=draft)
    await _advance_to(message.answer, state, next_state, next_prompt)


# ---------------------------------------------------------------------------
# Steps 3–9 — numeric inputs (all optional, each has a skip button)
# ---------------------------------------------------------------------------

@router.message(StateFilter(FdrStates.planned_readiness))
async def msg_planned_readiness(message: Message, state: FSMContext) -> None:
    await _handle_float_step(message, state, "planned_readiness")


@router.message(StateFilter(FdrStates.hours_remaining))
async def msg_hours_remaining(message: Message, state: FSMContext) -> None:
    await _handle_float_step(message, state, "hours_remaining")


@router.message(StateFilter(FdrStates.etc_hours))
async def msg_etc_hours(message: Message, state: FSMContext) -> None:
    await _handle_float_step(message, state, "etc_hours")


@router.message(StateFilter(FdrStates.next_act_amount))
async def msg_next_act_amount(message: Message, state: FSMContext) -> None:
    await _handle_float_step(message, state, "next_act_amount")


@router.message(StateFilter(FdrStates.next_act_date))
async def msg_next_act_date(message: Message, state: FSMContext) -> None:
    from datetime import date as _date
    raw = message.text.strip()
    try:
        _date.fromisoformat(raw)
    except ValueError:
        await message.answer(
            "⚠️ Введіть дату у форматі <b>РРРР-ММ-ДД</b>, наприклад: <b>2026-06-20</b>\n"
            "Або натисніть «пропустити».",
            parse_mode="HTML",
        )
        return
    draft_key, next_state, next_prompt = _SKIP_STATE_CHAIN["next_act_date"]
    data = await state.get_data()
    draft = data.get("draft", {})
    draft[draft_key] = raw
    await state.update_data(draft=draft)
    await _advance_to(message.answer, state, next_state, next_prompt)


@router.message(StateFilter(FdrStates.planned_margin))
async def msg_planned_margin(message: Message, state: FSMContext) -> None:
    await _handle_float_step(message, state, "planned_margin")


@router.message(StateFilter(FdrStates.forecast_margin))
async def msg_forecast_margin(message: Message, state: FSMContext) -> None:
    await _handle_float_step(message, state, "forecast_margin")


# ---------------------------------------------------------------------------
# Steps 10–11 — free-text inputs (all optional)
# ---------------------------------------------------------------------------

@router.message(StateFilter(FdrStates.plan_next_week))
async def msg_plan_next_week(message: Message, state: FSMContext) -> None:
    await _handle_text_step(message, state, "plan_next_week")


@router.message(StateFilter(FdrStates.comments))
async def msg_comments(message: Message, state: FSMContext) -> None:
    await _handle_text_step(message, state, "comments")


@router.message(StateFilter(FdrStates.problems))
async def msg_problems(message: Message, state: FSMContext) -> None:
    await _handle_text_step(message, state, "problems")


# ---------------------------------------------------------------------------
# Step 11b — help_needed (yes / no inline)
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(FdrStates.help_needed), F.data.startswith("fdr_yn:"))
async def cb_help_needed(call: CallbackQuery, state: FSMContext) -> None:
    answer = "yes" if call.data.endswith(":yes") else "no"
    data = await state.get_data()
    draft = data.get("draft", {})
    draft["help_needed"] = answer
    await state.update_data(draft=draft)
    await call.message.edit_reply_markup(reply_markup=None)
    await _show_confirm(call.message.answer, state)
    await call.answer()


# ---------------------------------------------------------------------------
# Confirm step
# ---------------------------------------------------------------------------

def _build_confirm_text(proj_code: str, draft: dict) -> str:
    yn = {"yes": "Так ⚠️", "no": "Ні"}.get(draft.get("help_needed", ""), "—")
    lines = [f"📋 <b>Проект {proj_code} — перевірте дані:</b>\n"]
    lines += [
        f"Фактична готовність:     <b>{_fmt(draft.get('actual_readiness_pct'), '%')}</b>",
        f"Планова готовність:      <b>{_fmt(draft.get('planned_readiness_pct'), '%')}</b>",
        f"Год. до кінця (план):    <b>{_fmt(draft.get('planned_hours_remaining'), ' год')}</b>",
        f"ETC год.:                <b>{_fmt(draft.get('etc_hours'), ' год')}</b>",
        f"Наступний акт:           <b>{_fmt(draft.get('next_act_amount'), ' грн', money=True)}</b>",
        f"Дата акту:               <b>{_fmt(draft.get('next_act_date'))}</b>",
        f"Планова маржа:           <b>{_fmt(draft.get('planned_margin_pct'), '%')}</b>",
        f"Прогнозна маржа:         <b>{_fmt(draft.get('forecast_margin_pct'), '%')}</b>",
        f"План на тиждень:         <b>{_fmt(draft.get('plan_next_week'))}</b>",
        f"Коментарі:               <b>{_fmt(draft.get('comments'))}</b>",
        f"Проблеми:                <b>{_fmt(draft.get('problems'))}</b>",
        f"Потрібна допомога:       <b>{yn}</b>",
    ]
    return "\n".join(lines)


async def _show_confirm(answer_fn, state: FSMContext) -> None:
    data = await state.get_data()
    draft = data.get("draft", {})
    proj_code = data.get("current_project_code", "?")
    text = _build_confirm_text(proj_code, draft)
    await answer_fn(
        text + "\n\n<i>Все вірно?</i>",
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(),
    )
    await state.set_state(FdrStates.confirm)


# ---------------------------------------------------------------------------
# Save — persist to DB + Google Sheets, then loop back to project list
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(FdrStates.confirm), F.data == "fdr_save")
async def cb_save(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    draft: dict = data.get("draft", {})
    week: str = data.get("week", "")
    proj_id: int = data.get("current_project_id")
    proj_code: str = data.get("current_project_code", "")
    pending_ids: list[int] = list(data.get("pending_ids", []))

    # Persist to SQLite
    await upsert_weekly_fdr(
        project_id=proj_id,
        pm_id=call.from_user.id,
        week_date=week,
        row_status="filled",
        **draft,
    )

    # Remove this project from the pending list
    pending_ids = [pid for pid in pending_ids if pid != proj_id]
    await state.update_data(
        pending_ids=pending_ids,
        current_project_id=None,
        current_project_code=None,
        draft={},
    )

    await call.message.edit_reply_markup(reply_markup=None)

    if not pending_ids:
        await call.message.answer("🎉 Всі проекти заповнені! Дякую за звіт.")
        await state.clear()
    else:
        remaining = await get_projects_for_pm(call.from_user.id, status="active")
        remaining = [p for p in remaining if p.id in pending_ids]
        await state.set_state(FdrStates.choosing_project)
        await call.message.answer(
            f"✅ Збережено!\n\nЗалишилось: <b>{len(remaining)}</b> проект(ів)\n\nОберіть наступний:",
            parse_mode="HTML",
            reply_markup=_projects_keyboard(remaining),
        )

    await call.answer()


# ---------------------------------------------------------------------------
# Redo — clear draft, restart from step 1 for the same project
# ---------------------------------------------------------------------------

@router.callback_query(StateFilter(FdrStates.confirm), F.data == "fdr_redo")
async def cb_redo(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    proj_code = data.get("current_project_code", "?")
    await state.update_data(draft={})
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"🔄 Починаємо заново для <b>{proj_code}</b>\n\n"
        f"<b>Крок 1/11.</b> Фактична готовність проекту, %\n"
        f"(Введіть число від 0 до 100)",
        parse_mode="HTML",
    )
    await state.set_state(FdrStates.actual_readiness)
    await call.answer()
