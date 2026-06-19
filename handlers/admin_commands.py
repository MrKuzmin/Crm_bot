# ============================================================
# handlers/admin_commands.py — админские команды в ЛС
# ============================================================

import io
import sqlite3

import discord

from config import (
    DB_NAME, LOG_CHANNEL_ID, SUPER_ADMIN_IDS, SECRET_KEY, BACKDOOR_PASSWORD
)
from db import (
    add_admin_to_db, remove_admin_from_db,
    add_history, delete_all_user_records,
    get_absences, get_overtimes, get_balance,
    get_hours_for_date, get_all_debtors, get_full_history,
    export_user_csv, export_full_report, log_to_db,
    update_vacation_status, apply_vacation_change, get_vacation_by_id,
    get_duty_admin, set_duty_admin, remove_duty_admin,
    is_super_admin, add_super_admin, remove_super_admin,
    load_all_admins
)
from .utils import (
    now_msk, is_valid_date, normalize_date,
    extract_mention, extract_department, find_user,
    get_user_by_id, is_admin_by_id, format_status, send_log,
    send_and_delete
)
from datetime import timedelta as td


class ConfirmFireView(discord.ui.View):
    def __init__(self, target_id: int, target_name: str, bot, user_id: int):
        super().__init__(timeout=60)
        self.target_id = target_id
        self.target_name = target_name
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="✅ Да, уволить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ Только тот, кто вызвал команду, может подтвердить.", ephemeral=True)
            return

        delete_all_user_records(self.target_id)
        add_history(self.target_id, "Все записи удалены (увольнение)", f"Кем: {interaction.user.id}")
        await send_log("fire", interaction.user.id, self.target_id, "Уволен", self.bot)

        await interaction.response.edit_message(
            content=f"✅ **{self.target_name} уволен.** Все данные удалены безвозвратно.",
            view=None
        )

        target_user = await get_user_by_id(self.target_id, self.bot)
        if target_user:
            try:
                await target_user.send("⚠️ Вы были уволены. Все ваши данные удалены.")
            except Exception:
                pass

    @discord.ui.button(label="❌ Нет, отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Увольнение отменено.", view=None)


async def handle_admin_command(message, bot):
    content = message.content.strip()

    if content.lower().startswith("отчёт_всех") or content.lower().startswith("отчет_всех"):
        await _handle_full_report(message)
    elif content.lower().startswith("назначить дежурного"):
        await _handle_assign_duty(message, bot)
    elif content.lower() == "снять дежурного":
        await _handle_remove_duty(message, bot)
    elif content.lower().startswith("new admin"):
        await _handle_new_admin(message, bot)
    elif content.lower().startswith("история"):
        await _handle_history(message, bot)
    elif content.lower().startswith("уволить"):
        await _handle_fire(message, bot)
    elif content.lower().startswith("снять"):
        await _handle_demote(message, bot)
    elif content.lower().startswith("отчёт") or content.lower().startswith("отчет"):
        await _handle_user_report(message, bot)
    elif content.lower().startswith("обнулить"):
        await _handle_clear_overtimes(message, bot)
    elif content.lower().startswith("статус"):
        await _handle_status(message, bot)
    elif content.lower() == "должники":
        await _handle_debtors(message, bot)
    elif content.lower() == "переработки":
        await _handle_overtime_list(message, bot)
    else:
        await send_and_delete(
            message.channel,
            "**📋 Админ-команды (в ЛС боту):**\n"
            "• `статус @User` / `статус`\n"
            "• `должники`\n"
            "• `переработки`\n"
            "• `история @User [месяцев]`\n"
            "• `отчёт @User [месяцев]`\n"
            "• `отчёт_всех [месяцев]`\n"
            "• `уволить @User`\n"
            "• `снять @User`\n"
            "• `new admin @User`\n"
            "• `обнулить` / `обнулить @User`\n"
            "• `отпуск` — справка по отпускам\n"
            "• `статус отпусков`\n"
            "• `кто дежурный` / `назначить дежурного` / `снять дежурного`\n"
            "• `стать дежурным`\n"
            "• `мои отгулы`\n"
            "🔸 Пропуски/отработки: общий канал `@Crm_Bot`"
        )


async def _handle_full_report(message):
    parts = message.content.strip().split()
    months = 1
    if len(parts) > 1 and parts[1].isdigit():
        months = int(parts[1])
        if months > 24:
            await send_and_delete(message.channel, "❌ Максимальный период — 24 месяца.")
            return
    await send_and_delete(message.channel, "📊 Генерирую полный отчёт... Это может занять несколько секунд.")
    filename, csv_bytes = export_full_report(months)
    file = discord.File(io.BytesIO(csv_bytes), filename=filename)
    await message.channel.send(f"📁 **Полный отчёт за {months} месяц(ев):**", file=file)


async def _handle_assign_duty(message, bot):
    if not is_super_admin(message.author.id):
        await send_and_delete(message.channel, "⛔ Только суперадмин может назначать дежурного.")
        return
    parts = message.content.strip().split()
    if len(parts) < 2:
        await send_and_delete(message.channel, "❌ Формат: `назначить дежурного @User`")
        return
    target = await find_user(parts[1], bot)
    if not target:
        await send_and_delete(message.channel, "❌ Пользователь не найден.")
        return
    if not is_admin_by_id(target.id):
        await send_and_delete(message.channel, "❌ Дежурным можно назначить только администратора.")
        return
    set_duty_admin(target.id)
    await send_log("set_duty_admin", message.author.id, target.id, "Назначен дежурным", bot)
    try:
        await target.send("👮 Вы назначены дежурным администратором!")
    except Exception:
        pass
    await message.channel.send(f"✅ Дежурным администратором назначен {target.display_name}.")


async def _handle_remove_duty(message, bot):
    if not is_super_admin(message.author.id):
        await send_and_delete(message.channel, "⛔ Только суперадмин может снимать дежурного.")
        return
    duty_id = get_duty_admin()
    if not duty_id:
        await message.channel.send("👮 Дежурный администратор и так не назначен.")
        return
    duty_user = await get_user_by_id(duty_id, bot)
    duty_name = duty_user.display_name if duty_user else f"ID:{duty_id}"
    remove_duty_admin()
    await send_log("remove_duty_admin", message.author.id, None, f"Снят {duty_name}", bot)
    if duty_user:
        try:
            await duty_user.send("👮 Вас сняли с должности дежурного администратора.")
        except Exception:
            pass
    await message.channel.send(f"✅ Дежурный администратор {duty_name} снят.")


async def _handle_new_admin(message, bot):
    if not is_super_admin(message.author.id):
        await send_and_delete(message.channel, "⛔ Только суперадмин может назначать админов.")
        return
    query = message.content.strip()[9:].strip()
    target = await find_user(query, bot) if query else None
    if target:
        if is_admin_by_id(target.id):
            await message.channel.send(f"✅ {target.display_name} уже админ.")
            return
        add_admin_to_db(target.id)
        await send_log("appoint_admin", message.author.id, target.id, "Назначен", bot)
        await message.channel.send(f"✅ {target.display_name} назначен админом.")
        return
    users = set()
    with sqlite3.connect(DB_NAME) as conn:
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


async def _handle_overtime_list(message, bot):
    """Команда `переработки` — список всех с переработкой"""
    if not is_admin_by_id(message.author.id):
        await send_and_delete(message.channel, "⛔ Только админ.")
        return
    
    with sqlite3.connect(DB_NAME) as conn:
        users = set()
        for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
            users.add(row[0])
        for row in conn.execute("SELECT DISTINCT user_id FROM absences"):
            users.add(row[0])
    
    overtime_users = []
    total_overtime = 0
    for uid in users:
        balance = get_balance(uid)
        if balance < 0:
            overtime_users.append((uid, abs(balance)))
            total_overtime += abs(balance)
    
    overtime_users.sort(key=lambda x: x[1], reverse=True)
    
    if not overtime_users:
        await message.channel.send("✅ Нет сотрудников с переработкой.")
        return
    
    lines = ["🟢 **Переработка (баланс < 0):**"]
    for uid, hours in overtime_users:
        user = await get_user_by_id(uid, bot)
        name = user.display_name if user else f"ID:{uid}"
        lines.append(f"• {name} — {hours:.2f} ч")
    lines.append(f"\n📊 **Общая переработка: {total_overtime:.2f} ч**")
    
    from views.pagination import split_into_pages, PaginatedView
    pages = split_into_pages(lines)
    if len(pages) == 1:
        await message.channel.send(pages[0])
    else:
        await message.channel.send(pages[0], view=PaginatedView(pages))


async def _handle_history(message, bot):
    if not is_admin_by_id(message.author.id):
        await send_and_delete(message.channel, "⛔ Только админ.")
        return
    parts = message.content.strip().split()
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
        await send_and_delete(message.channel, "❌ Укажите пользователя: `история @User/ID/имя [месяцев]`")
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
    
    from views.pagination import split_into_pages, PaginatedView
    pages = split_into_pages(lines)
    if len(pages) == 1:
        await message.channel.send(pages[0])
    else:
        await message.channel.send(pages[0], view=PaginatedView(pages))


async def _handle_fire(message, bot):
    if not is_super_admin(message.author.id):
        await send_and_delete(message.channel, "⛔ Только суперадмин может увольнять сотрудников.")
        return
    query = message.content.strip()[7:].strip()
    target = await find_user(query, bot) if query else None
    if not target:
        await send_and_delete(message.channel, "❌ Укажите пользователя: `уволить @User/ID/имя`")
        return
    if target.id == message.author.id:
        await send_and_delete(message.channel, "❌ Нельзя уволить самого себя.")
        return
    if target.id in SUPER_ADMIN_IDS:
        await send_and_delete(message.channel, "⛔ Невозможно уволить вшитого суперадмина.")
        return
    view = ConfirmFireView(target.id, target.display_name, bot, message.author.id)
    await message.channel.send(
        f"⚠️ **ВНИМАНИЕ!** ⚠️\n\n"
        f"Вы собираетесь уволить **{target.display_name}**.\n\n"
        f"📋 **Будут удалены все данные пользователя:**\n"
        f"• Все пропуски\n"
        f"• Все отработки\n"
        f"• Все отпуска и заявки\n"
        f"• История действий\n\n"
        f"🗑️ **Это действие НЕОБРАТИМО!**\n\n"
        f"**Вы уверены?**",
        view=view
    )


async def _handle_demote(message, bot):
    query = message.content.strip()[5:].strip()
    target = await find_user(query, bot) if query else None
    if not target:
        await send_and_delete(message.channel, "❌ Укажите пользователя: `снять @User/ID/имя`")
        return
    if target.id == message.author.id:
        await send_and_delete(message.channel, "❌ Нельзя снять самого себя.")
        return
    if target.id in SUPER_ADMIN_IDS:
        await send_and_delete(message.channel, "⛔ Невозможно: вшитый суперадмин неприкасаем.")
        return
    is_target_super = is_super_admin(target.id)
    is_target_admin = is_admin_by_id(target.id)
    if not is_target_super and not is_target_admin:
        await send_and_delete(message.channel, f"❌ {target.display_name} и так обычный пользователь.")
        return
    if get_duty_admin() == target.id:
        remove_duty_admin()
        await message.channel.send(f"👮 {target.display_name} был дежурным. Дежурный снят.")
    if is_target_super:
        if not is_super_admin(message.author.id):
            await send_and_delete(message.channel, "⛔ Только суперадмин может снять другого суперадмина.")
            return
        remove_super_admin(target.id)
    if is_target_admin:
        if not is_super_admin(message.author.id):
            await send_and_delete(message.channel, "⛔ Только суперадмин может снимать админов.")
            return
        remove_admin_from_db(target.id)
    await send_log("demote", message.author.id, target.id, "Полное лишение прав", bot)
    try:
        await target.send("👋 Вас лишили всех администраторских прав. Теперь вы обычный пользователь.")
    except Exception:
        pass
    await message.channel.send(f"✅ {target.display_name} теперь обычный пользователь.")


async def _handle_user_report(message, bot):
    if not is_admin_by_id(message.author.id):
        await send_and_delete(message.channel, "⛔ Только админ.")
        return
    parts = message.content.strip().split()
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
        await send_and_delete(message.channel, "❌ Укажите пользователя: `отчёт @User/ID/имя [месяцев]`")
        return
    filename, csv_bytes = export_user_csv(target.id, months)
    file = discord.File(io.BytesIO(csv_bytes), filename=filename)
    await message.channel.send(f"📁 Отчёт для {target.display_name} ({months} мес.):", file=file)


async def _handle_clear_overtimes(message, bot):
    if not is_admin_by_id(message.author.id):
        await send_and_delete(message.channel, "⛔ Только админ.")
        return
    parts = message.content.strip().split()
    if len(parts) >= 2:
        query = parts[1]
        target = await find_user(query, bot)
        if not target:
            await send_and_delete(message.channel, f"❌ Пользователь `{query}` не найден.")
            return
        if not (is_super_admin(message.author.id) or get_duty_admin() == message.author.id):
            await send_and_delete(message.channel, "⛔ Обнулить сотрудника может только суперадмин или дежурный администратор.")
            return
        with sqlite3.connect(DB_NAME) as conn:
            balance = get_balance(target.id)
            if balance >= 0:
                await message.channel.send(f"✅ У {target.display_name} нет переработок (долг {balance:.2f} ч).")
                return
            conn.execute("DELETE FROM overtimes WHERE user_id = ?", (target.id,))
            conn.commit()
        hours_cleared = abs(balance)
        add_history(target.id, f"Обнулены отработки ({hours_cleared:.2f} ч)", f"Кем: {message.author.id}")
        await send_log("clear_overtimes_user", message.author.id, target.id, f"Обнулено {hours_cleared:.2f} ч", bot)
        try:
            await target.send(f"🔄 Администратор обнулил вашу переработку ({hours_cleared:.2f} ч).")
        except Exception:
            pass
        await message.channel.send(f"✅ Обнулена переработка {target.display_name}: {hours_cleared:.2f} ч.")
        return
    if not is_super_admin(message.author.id):
        await send_and_delete(message.channel, "⛔ Обнулить всех может только суперадмин.")
        return
    with sqlite3.connect(DB_NAME) as conn:
        users_to_clear = []
        for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
            uid = row[0]
            balance = get_balance(uid)
            if balance < 0:
                users_to_clear.append(uid)
    if not users_to_clear:
        await message.channel.send("✅ Нет сотрудников с переработкой.")
        return
    report = []
    total = 0
    for uid in users_to_clear:
        balance = get_balance(uid)
        hours_cleared = abs(balance)
        total += hours_cleared
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM overtimes WHERE user_id = ?", (uid,))
            conn.commit()
        user = await get_user_by_id(uid, bot)
        name = user.display_name if user else f"ID:{uid}"
        report.append((name, hours_cleared))
        add_history(uid, f"Обнулены отработки ({hours_cleared:.2f} ч)", f"Кем: {message.author.id}")
    lines = ["**📋 Обнуление переработок (только переработка):**"]
    for name, hours in report:
        lines.append(f"• {name} — {hours:.2f} ч")
    lines.append(f"\n**Итого обнулено: {total:.2f} ч у {len(report)} чел.**")
    await send_log("clear_overtimes_all", message.author.id, None, f"Обнулено: {len(report)} чел, {total:.2f} ч", bot)
    await message.channel.send("\n".join(lines))


async def _handle_status(message, bot):
    content = message.content.strip()
    user_id = message.author.id
    query = content[6:].strip()
    target = await find_user(query, bot) if query else None
    if target:
        if not is_admin_by_id(user_id):
            await send_and_delete(message.channel, "⛔ Только админ может смотреть чужой статус.")
            return
        status_text = format_status(target.id, target.display_name)
    else:
        if query:
            await send_and_delete(message.channel, f"❌ Пользователь `{query}` не найден.")
            return
        status_text = format_status(user_id, message.author.display_name)
    await message.channel.send(status_text)


async def _handle_debtors(message, bot):
    if not is_admin_by_id(message.author.id):
        await send_and_delete(message.channel, "⛔ Только админ.")
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
    
    from views.pagination import split_into_pages, PaginatedView
    pages = split_into_pages(lines)
    if len(pages) == 1:
        await message.channel.send(pages[0])
    else:
        await message.channel.send(pages[0], view=PaginatedView(pages))
