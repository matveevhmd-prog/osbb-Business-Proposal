"""Admin commands — accessible to users with role 'admin' or 'owner'."""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Config
from database.queries import (
    User,
    get_all_pms,
    get_project_by_code,
    get_user,
    insert_project,
    update_project_field,
    upsert_user,
)

logger = logging.getLogger(__name__)
router = Router()

_ADMIN_ROLES = {"admin", "owner"}


async def _is_admin(message: Message, config: Config) -> bool:
    # Owner from config is always trusted — bootstraps the first /adduser
    if message.from_user.id == config.owner_telegram_id:
        return True
    user = await get_user(message.from_user.id)
    if user and user.role in _ADMIN_ROLES:
        return True
    await message.answer("⛔ Ця команда лише для адміністраторів.")
    return False


# ---------------------------------------------------------------------------
# /adduser <telegram_id> <name> <role>
# ---------------------------------------------------------------------------

@router.message(Command("adduser"))
async def cmd_adduser(message: Message, config: Config) -> None:
    if not await _is_admin(message, config):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer(
            "Використання:\n"
            "<code>/adduser &lt;telegram_id&gt; &lt;ім'я&gt; &lt;роль&gt;</code>\n\n"
            "Ролі: <code>owner | pm | executor | admin</code>",
            parse_mode="HTML",
        )
        return

    _, tid_str, name, role = parts
    valid_roles = {"owner", "pm", "executor", "admin"}

    try:
        tid = int(tid_str)
    except ValueError:
        await message.answer("⚠️ telegram_id має бути числом.")
        return

    if role not in valid_roles:
        await message.answer(
            f"⚠️ Невідома роль. Допустимі: <code>{' | '.join(sorted(valid_roles))}</code>",
            parse_mode="HTML",
        )
        return

    await upsert_user(User(telegram_id=tid, name=name, role=role))
    await message.answer(
        f"✅ Користувач збережений:\n"
        f"ID: <code>{tid}</code>  Ім'я: <b>{name}</b>  Роль: <b>{role}</b>",
        parse_mode="HTML",
    )
    logger.info("Admin %d upserted user %d (%s, %s)", message.from_user.id, tid, name, role)


# ---------------------------------------------------------------------------
# /addproject <code> <name> <pm_id> <contract> <hours> <margin_%> [date]
# ---------------------------------------------------------------------------

@router.message(Command("addproject"))
async def cmd_addproject(message: Message, config: Config) -> None:
    if not await _is_admin(message, config):
        return

    parts = message.text.split(maxsplit=7)
    if len(parts) < 7:
        await message.answer(
            "Використання:\n"
            "<code>/addproject &lt;код&gt; &lt;назва&gt; &lt;pm_id&gt; "
            "&lt;сума_договору&gt; &lt;год_план&gt; &lt;маржа_%&gt; [РРРР-ММ-ДД]</code>\n\n"
            "Приклад:\n"
            "<code>/addproject ARCH-01 Садиба 123456789 500000 1200 30 2026-12-31</code>",
            parse_mode="HTML",
        )
        return

    _, code, name, pm_id_str, total_str, hours_str, margin_str, *rest = parts
    completion_date: Optional[str] = rest[0] if rest else None

    try:
        pm_id = int(pm_id_str)
        contract_total = float(total_str.replace(",", "."))
        planned_hours = float(hours_str.replace(",", "."))
        planned_margin = float(margin_str.replace(",", "."))
    except ValueError:
        await message.answer("⚠️ pm_id, сума, години та маржа мають бути числами.")
        return

    pm = await get_user(pm_id)
    if pm is None:
        await message.answer(
            f"⚠️ PM <code>{pm_id}</code> не знайдений. "
            f"Спочатку додайте через /adduser.",
            parse_mode="HTML",
        )
        return

    try:
        proj_id = await insert_project(
            code=code.upper(),
            name=name,
            pm_id=pm_id,
            contract_total=contract_total,
            planned_hours=planned_hours,
            planned_margin_pct=planned_margin,
            planned_completion_date=completion_date,
        )
    except Exception as exc:
        await message.answer(f"⚠️ Помилка збереження: {exc}")
        return

    await message.answer(
        f"✅ Проект додано (id={proj_id}):\n"
        f"Код: <b>{code.upper()}</b>  PM: <b>{pm.name}</b>\n"
        f"Договір: <b>{contract_total:,.0f} грн</b>  "
        f"Год.: <b>{planned_hours:.0f}</b>  Маржа: <b>{planned_margin:.1f}%</b>",
        parse_mode="HTML",
    )
    logger.info("Admin %d added project %s", message.from_user.id, code.upper())


# ---------------------------------------------------------------------------
# /setplan <code> <field> <value>
# ---------------------------------------------------------------------------

@router.message(Command("setplan"))
async def cmd_setplan(message: Message, config: Config) -> None:
    if not await _is_admin(message, config):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer(
            "Використання:\n"
            "<code>/setplan &lt;код&gt; &lt;поле&gt; &lt;значення&gt;</code>\n\n"
            "Поля: <code>name | contract_total | planned_hours | "
            "planned_margin_pct | planned_completion_date | status</code>",
            parse_mode="HTML",
        )
        return

    _, code, field, raw_value = parts
    numeric_fields = {"contract_total", "planned_hours", "planned_margin_pct"}
    value: object = raw_value
    if field in numeric_fields:
        try:
            value = float(raw_value.replace(",", "."))
        except ValueError:
            await message.answer(f"⚠️ Поле <code>{field}</code> має бути числом.", parse_mode="HTML")
            return

    try:
        updated = await update_project_field(code.upper(), field, value)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return

    if updated:
        await message.answer(
            f"✅ <b>{code.upper()}</b>.<code>{field}</code> → <code>{value}</code>",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"⚠️ Проект <code>{code.upper()}</code> не знайдений.",
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# /trigger_fdr  — manually fire FDR for all PMs (testing / emergency)
# ---------------------------------------------------------------------------

@router.message(Command("trigger_fdr"))
async def cmd_trigger_fdr(message: Message, config: Config, storage) -> None:
    if not await _is_admin(message, config):
        return

    from handlers.fdr_flow import start_fdr_for_pm

    pms = await get_all_pms()
    if not pms:
        await message.answer("⚠️ Немає жодного PM в базі. Додайте через /adduser.")
        return

    await message.answer(f"▶️ Запускаю FDR для {len(pms)} PM(ів)…")
    count = 0
    for pm in pms:
        try:
            await start_fdr_for_pm(message.bot, pm.telegram_id, storage)
            count += 1
        except Exception as exc:
            logger.warning("trigger_fdr PM %d: %s", pm.telegram_id, exc)
            await message.answer(f"⚠️ {pm.name}: {exc}")

    await message.answer(f"✅ FDR запущено для {count}/{len(pms)} PM.")


# ---------------------------------------------------------------------------
# /trigger_summary — manually send AI summary to owner (testing)
# ---------------------------------------------------------------------------

@router.message(Command("trigger_summary"))
async def cmd_trigger_summary(message: Message, config: Config) -> None:
    if not await _is_admin(message, config):
        return

    await message.answer("⏳ Генерую AI-summary…")
    try:
        from ai.summary import generate_summary
        text = await generate_summary(config)
        await message.bot.send_message(
            chat_id=config.owner_telegram_id,
            text=text,
            parse_mode="HTML",
        )
        await message.answer(
            f"✅ Summary надіслано власнику (ID <code>{config.owner_telegram_id}</code>).",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("trigger_summary failed")
        await message.answer(f"⚠️ Помилка: {exc}")
