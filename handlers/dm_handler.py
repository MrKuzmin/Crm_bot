# ============================================================
# handlers/dm_handler.py — обработка личных сообщений
# ============================================================

import io
import re
import sqlite3
from datetime import timedelta as td

import discord

from config import (
    LOG_CHANNEL_ID, SUPER_ADMIN_IDS, SECRET_KEY,
    MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY, DB_NAME
)
from db import (
    add_admin_to_db, remove_admin_from_db,
    add_absence, add_overtime, add_history,
    delete_absence, delete_overtime, delete_all_user_records,
    get_absences, get_overtimes, get_balance,
    get_hours_for_date, get_all_debtors, get_full_history,
    export_user_csv, log_to_db,
    add_vacation_request, get_vacation_by_id, check_existing_vacation,
    request_vacation_change, update_vacation_status, apply_vacation_change,
    admin_change_vacation, delete_vacation_db, get_all_active_vacations
)

from .vacation_handler import handle_vacation_command
from .utils import (
    now_msk, is_valid_date, normalize_date,
    extract_mention, extract_department, find_user,
    get_user_by_id, is_admin, format_status, send_log
)


async def handle_dm(message: discord.Message, bot, current_admins: list, vacation_view_class):
    """Точка входа для всех личных сообщений"""
    content = message.content.strip()
    user_id = message.author.id

    # Отпуска и связанные команды
    if any(content.lower().startswith(cmd) for cmd in ["отпуск", "изменить отпуск", "мои отпуска", "статус отпусков"]):
        return await handle_vacation_command(message, bot, current_admins, vacation_view_class)

    # --- new admin ---
    if content.lower().startswith("new admin"):
        if not is_admin(user_id, current_admins):
            await message.channel.send("⛔ Только admin может назначать админов.")
            return
        query = content[9:].strip()
        target = await find_user(query, bot) if query else None
        if target:
            if target.id in current_admins:
                await message.channel.send(f"✅ {target.display_name} уже админ.")
                return
            add_admin_to_db(target.id)
            current_admins.append(target.id)
            await send_log("appoint_admin", user_id, target.id, "Назначен", bot)
            await message.channel.send(f"✅ {target.display_name} назначен админом.")
            return
        with sqlite3.connect(DB_NAME) as conn:
            users = set()
            for row in conn.execute("SELECT DISTINCT user_id FROM absences"):
                users.add(row[0])
            for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
                users.add(row[0])
        if not users:
            await message.channel.send("В базе пока нет пользователей.")
            return
        lines = ["**👤 Пользователи в базе:**"]
        for uid in users:
            user = await get_user_by_id(uid, bot)
            name = user.mention if user else f"ID:{uid}"
            lines.append(f"• {name}")
        lines.append("\nНапишите `new admin @User` чтобы назначить.")
        await message.channel.send("\n".join(lines))
        return

    # --- стать админом ---
    if content.lower().startswith("стать админом"):
        parts = content.split()
        if len(parts) < 3:
            await message.channel.send("❌ Формат: `стать админом *ключ*`")
            return
        if parts[2] != SECRET_KEY:
            await message.channel.send("❌ Неверный ключ.")
            return
        if user_id in current_admins:
            await message.channel.send("✅ Вы уже админ.")
            return
        add_admin_to_db(user_id)
        current_admins.append(user_id)
        await send_log("became_admin", user_id, user_id, "Ключ", bot)
        await message.channel.send("✅ Вы стали админом!")
        return

    # --- статус ---
    if content.lower().startswith("статус"):
        query = content[6:].strip()
        target = await find_user(query, bot) if query else None
        if target:
            if not is_admin(user_id, current_admins):
                await message.channel.send("⛔ Только админ может смотреть чужой статус.")
                return
            status_text = format_status(target.id, target.display_name)
        else:
            if query:
                await message.channel.send(f"❌ Пользователь `{query}` не найден.")
                return
            status_text = format_status(user_id, message.author.display_name)
        await message.channel.send(status_text)
        return

    # --- должники ---
    if content.lower() == "должники":
        if not is_admin(user_id, current_admins):
            await message.channel.send("⛔ Только админ.")
            return
        debtors = get_all_debtors()
        if not debtors:
            await message.channel.send("✅ Никто не должен.")
            return
        lines = ["📋 **Должники:**"]
        for uid, debt in debtors:
            user = await get_user_by_id(uid, bot)
            name = user.display_name if user else f"ID:{uid}"
            lines.append(f"• {name} — {debt:.2f} ч")
        await message.channel.send("\n".join(lines))
        return

    # --- история ---
    if content.lower().startswith("история"):
        parts = content.split()
        months = 1
        query_parts = []
        for p in parts[1:]:
            if p.isdigit():
                months = int(p)
            else:
                query_parts.append(p)
        query = " ".join(query_parts).strip()
        target = await find_user(query, bot) if query else None
        if not target:
            await message.channel.send("❌ Укажите пользователя: `история @User/ID/имя [месяцев]`")
            return
        if not is_admin(user_id, current_admins):
            await message.channel.send("⛔ Только админ.")
            return
        cutoff = (now_msk() - td(days=months * 30)).strftime("%Y-%m-%d")
        records = get_full_history(target.id)
        filtered = [(date, hours, rtype) for date, hours, rtype in records if date >= cutoff or rtype.startswith("⚡")]
        if not filtered:
            await message.channel.send(f"У {target.display_name} нет записей за {months} мес.")
            return
        lines = [f"📜 **История: {target.display_name} ({months} мес.)**"]
        for date, hours, rtype in filtered:
            if rtype.startswith("⚡"):
                lines.append(f"{rtype} ({date})")
            else:
                emoji = "🔴" if rtype == "пропуск" else "🟢"
                lines.append(f"{emoji} {date} — {hours:.2f} ч ({rtype})")
        balance = get_balance(target.id)
        if balance > 0:
            lines.append(f"\n❌ Долг: {balance:.2f} ч")
        elif balance == 0:
            lines.append(f"\n✅ Долгов нет")
        else:
            lines.append(f"\n🟢 Переработка: {abs(balance):.2f} ч")
        await message.channel.send("\n".join(lines))
        return

    # --- уволить ---
    if content.lower().startswith("уволить"):
        query = content[7:].strip()
        target = await find_user(query, bot) if query else None
        if target:
            if not is_admin(user_id, current_admins):
                await message.channel.send("⛔ Только админ.")
                return
            delete_all_user_records(target.id)
            add_history(target.id, "Все записи удалены (увольнение)", f"Кем: {user_id}")
            await send_log("fire", user_id, target.id, "Уволен", bot)
            await message.channel.send(f"🗑️ Все записи {target.display_name} удалены.")
            return
        await message.channel.send("❌ Укажите пользователя: `уволить @User/ID/имя`")
        return

    # --- снять ---
    if content.lower().startswith("снять"):
        query = content[5:].strip()
        target = await find_user(query, bot) if query else None
        if target:
            if not is_admin(user_id, current_admins):
                await message.channel.send("⛔ Только админ.")
                return
            if target.id in SUPER_ADMIN_IDS:
                await message.channel.send("⛔ Нельзя снять суперадмина.")
                return
            if target.id in current_admins:
                remove_admin_from_db(target.id)
                current_admins.remove(target.id)
                await send_log("demote", user_id, target.id, "Снят", bot)
                await message.channel.send(f"✅ {target.display_name} снят с админов.")
            else:
                await message.channel.send(f"❌ {target.display_name} не админ.")
            return
        await message.channel.send("❌ Укажите пользователя: `снять @User/ID/имя`")
        return

    # --- отчёт ---
    if content.lower().startswith("отчёт") or content.lower().startswith("отчет"):
        parts = content.split()
        months = 1
        query_parts = []
        for p in parts[1:]:
            if p.isdigit():
                months = int(p)
            else:
                query_parts.append(p)
        query = " ".join(query_parts).strip()
        target = await find_user(query, bot) if query else None
        if not target:
            await message.channel.send("❌ Укажите пользователя: `отчёт @User/ID/имя [месяцев]`")
            return
        if not is_admin(user_id, current_admins):
            await message.channel.send("⛔ Только админ.")
            return
        filename, csv_bytes = export_user_csv(target.id, months)
        file = discord.File(io.BytesIO(csv_bytes), filename=filename)
        await message.channel.send(f"📁 Отчёт для {target.display_name} ({months} мес.):", file=file)
        return

    # --- обнулить ---
    if content.lower() == "обнулить":
        if not is_admin(user_id, current_admins):
            await message.channel.send("⛔ Только админ.")
            return
        with sqlite3.connect(DB_NAME) as conn:
            users = set()
            for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
                users.add(row[0])
        report = []
        with sqlite3.connect(DB_NAME) as conn:
            for uid in users:
                balance = get_balance(uid)
                if balance < 0:
                    conn.execute("DELETE FROM overtimes WHERE user_id = ?", (uid,))
                    user = await get_user_by_id(uid, bot)
                    name = user.display_name if user else f"ID:{uid}"
                    report.append((name, abs(balance)))
                    add_history(uid, f"Обнулены отработки ({abs(balance):.2f} ч)", f"Кем: {user_id}")
            conn.commit()
        if not report:
            await message.channel.send("✅ Нечего обнулять — ни у кого нет переработок.")
            return
        lines = ["**📋 Обнуление переработок:**"]
        total = 0
        for name, hours in report:
            lines.append(f"• {name} — {hours:.2f} ч")
            total += hours
        lines.append(f"\n**Итого обнулено: {total:.2f} ч у {len(report)} чел.**")
        await send_log("clear_overtimes", user_id, None, f"Обнулено: {len(report)} чел, {total:.2f} ч", bot)
        await message.channel.send("\n".join(lines))
        return

    # --- Подсказка ---
    if is_admin(user_id, current_admins):
        await message.channel.send(
            "**📋 Команды:**\n"
            "• `статус` / `статус @User/ID/имя`\n"
            "• `должники`\n"
            "• `история @User/ID/имя [месяцев]`\n"
            "• `уволить @User/ID/имя`\n"
            "• `снять @User/ID/имя`\n"
            "• `отчёт @User/ID/имя [месяцев]`\n"
            "• `new admin @User/ID/имя`\n"
            "• `обнулить`\n"
            "• `отпуск` — справка по отпускам\n"
            "• `статус отпусков` — отпуска по отделам\n\n"
            "🔸 Пропуски/отработки: общий канал `@Crm_Bot`"
        )
    else:
        await message.channel.send(
            "**📋 Команды:**\n"
            "• `статус` — ваша сводка\n"
            "• `отпуск` — справка по отпускам\n"
            "• `мои отпуска` — ваши даты отпуска\n\n"
            "🔸 Пропуски/отработки: общий канал `@Crm_Bot`"
        )