# ============================================================
# bot.py — Discord-бот Crm_Bot
# Вся логика команд, реакций, сообщений
# Настройки в config.py, работа с БД в db.py
# ============================================================

import asyncio
import io
import re
import sqlite3
from datetime import datetime, timezone, timedelta as td

import discord
from discord.ext import commands
from discord import app_commands

# Свои файлы
from config import (
    TOKEN, GENERAL_CHANNEL_ID, LOG_CHANNEL_ID,
    SUPER_ADMIN_IDS, SECRET_KEY,
    MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY, DB_NAME,
    TIMEZONE_OFFSET
)
from db import (
    init_db, load_all_admins, add_admin_to_db, remove_admin_from_db,
    add_absence, add_overtime, add_history,
    delete_absence, delete_overtime, delete_all_user_records,
    get_absences, get_overtimes, get_balance,
    get_hours_for_date, get_all_debtors, get_full_history,
    export_user_csv, log_to_db
)


# ============================================================
# МОСКОВСКОЕ ВРЕМЯ
# ============================================================

MSK = timezone(td(hours=TIMEZONE_OFFSET))


def now_msk() -> datetime:
    return datetime.now(MSK)


def today_msk() -> str:
    return now_msk().strftime("%d.%m.%Y")


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def is_valid_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
        return True
    except ValueError:
        return False


def parse_date(text: str) -> str:
    text = text.lower().strip()
    today = now_msk()
    if text == "сегодня":
        return today.strftime("%d.%m.%Y")
    elif text == "вчера":
        return (today - td(days=1)).strftime("%d.%m.%Y")
    elif text == "завтра":
        return (today + td(days=1)).strftime("%d.%m.%Y")
    elif is_valid_date(text):
        return text
    return None


def extract_mention(content: str):
    match = re.search(r'<@!?(\d+)>', content)
    if match:
        return int(match.group(1))
    return None


async def find_user(query: str):
    if not query:
        return None
    uid = extract_mention(query)
    if uid:
        user = await get_user_by_id(uid)
        if user:
            return user
    if query.isdigit():
        user = await get_user_by_id(int(query))
        if user:
            return user
    for guild in bot.guilds:
        for member in guild.members:
            if member.name.lower() == query.lower():
                return member
            if member.display_name.lower() == query.lower():
                return member
            if str(member).lower() == query.lower():
                return member
    for guild in bot.guilds:
        for member in guild.members:
            if query.lower() in member.name.lower() or query.lower() in member.display_name.lower():
                return member
    return None


# ============================================================
# НАСТРОЙКА БОТА
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

current_admins = []


# ============================================================
# ЗАПУСК БОТА
# ============================================================

@bot.event
async def on_ready():
    global current_admins
    init_db()
    current_admins = load_all_admins()
    try:
        synced = await bot.tree.sync()
        print(f"✅ Бот {bot.user} запущен. Синхронизировано {len(synced)} слеш-команд.")
        print(f"👑 Админы: {current_admins}")
        print(f"📋 Общий канал ID: {GENERAL_CHANNEL_ID}")
        print(f"📋 Лог-канал ID: {LOG_CHANNEL_ID}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def is_admin(user_id: int) -> bool:
    return user_id in current_admins


async def get_user_by_id(user_id: int):
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member:
            return member
    try:
        return await bot.fetch_user(user_id)
    except:
        return None


def format_status(user_id: int, user_name: str) -> str:
    absences = get_absences(user_id)
    overtimes = get_overtimes(user_id)
    balance = get_balance(user_id)
    lines = [f"📊 **Статус: {user_name}**\n"]
    if absences:
        lines.append("🔴 **Долги:**")
        for date, hours in absences:
            lines.append(f"• {date} — {hours:.2f} ч")
    else:
        lines.append("🔴 **Долги:** нет")
    lines.append("")
    if overtimes:
        lines.append("🟢 **Отработано:**")
        for date, hours in overtimes:
            lines.append(f"• {date} — {hours:.2f} ч")
    else:
        lines.append("🟢 **Отработано:** нет")
    lines.append("")
    if balance > 0:
        lines.append(f"❌ **Нужно отработать: {balance:.2f} ч**")
    elif balance == 0:
        lines.append("✅ **У вас нет долгов.**")
    else:
        lines.append(f"🟢 **У вас переработка: {abs(balance):.2f} ч**")
    return "\n".join(lines)


async def send_log(action: str, user_id: int, target_user_id: int = None, details: str = ""):
    log_line = log_to_db(user_id, action, target_user_id, details)
    print(log_line)
    if LOG_CHANNEL_ID and LOG_CHANNEL_ID != 0:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.send(f"`{log_line}`")
            except:
                pass


# ============================================================
# СЛЭШ-КОМАНДА /help
# ============================================================

@bot.tree.command(name="help", description="Правила работы с ботом")
async def slash_help(interaction: discord.Interaction):
    user_id = interaction.user.id
    is_user_admin = is_admin(user_id)
    is_dm = isinstance(interaction.channel, discord.DMChannel)
    text = (
        "**📋 Crm_Bot — учёт пропусков и отработок**\n\n"
        "**🔹 В общем канале (пишите с тегом @Crm_Bot):**\n"
        f"• `@Crm_Bot пропуск Ч` — пропуск на сегодня (макс {MAX_ABSENCE_PER_DAY} ч/день)\n"
        f"• `@Crm_Bot пропуск ДД.ММ.ГГГГ Ч` — пропуск на дату\n"
        f"• `@Crm_Bot пропуск сегодня/вчера/завтра Ч` — пропуск словами\n"
        f"• `@Crm_Bot отработка Ч` — отработка на сегодня (макс {MAX_OVERTIME_PER_DAY} ч/день)\n"
        f"• `@Crm_Bot отработка ДД.ММ.ГГГГ Ч` — отработка на дату\n"
        f"• `@Crm_Bot отработка сегодня/вчера/завтра Ч` — отработка словами\n"
        "• `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ` — удалить свою запись\n"
        "• Бот отвечает реакцией: ✅ успех, ❌ ошибка (с пояснением)\n\n"
        "**🔹 Лимиты:**\n"
        f"• Пропуск: ≤ {MAX_ABSENCE_PER_DAY} ч за одну дату\n"
        f"• Отработка: ≤ {MAX_OVERTIME_PER_DAY} ч за одну дату\n\n"
        "**🔹 Формула:** долги − отработки\n"
        "• > 0 → нужно отработать\n"
        "• = 0 → долгов нет\n"
        "• < 0 → переработка\n\n"
        "🕐 **Время:** Московское (МСК, UTC+3)"
    )
    if not is_dm:
        await interaction.response.send_message(text, ephemeral=True)
        return
    text += "\n\n**🔹 В личке (текстом):**\n• `статус` — ваша сводка\n"
    if is_user_admin:
        text += (
            "• `статус @User/ID/имя` — чужая сводка\n"
            "• `должники` — список должников\n"
            "• `история @User/ID/имя [месяцев]` — записи человека\n"
            "• `уволить @User/ID/имя` — удалить все записи\n"
            "• `снять @User/ID/имя` — снять админа\n"
            "• `отчёт @User/ID/имя [месяцев]` — экспорт в CSV\n"
            "• `new admin @User/ID/имя` — назначить админа\n"
            "• `обнулить` — обнулить переработки у всех\n"
            "• `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ @User` — удалить чужую запись"
        )
    await interaction.response.send_message(text, ephemeral=True)


# ============================================================
# ОБРАБОТЧИК СООБЩЕНИЙ
# ============================================================

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    content = message.content.strip()
    user_id = message.author.id

    # ============================================================
    # ЛИЧКА
    # ============================================================
    if isinstance(message.channel, discord.DMChannel):

        # --- new admin ---
        if content.lower().startswith("new admin"):
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ может назначать админов.")
                return
            query = content[9:].strip()
            target = await find_user(query) if query else None
            if target:
                if target.id in current_admins:
                    await message.channel.send(f"✅ {target.display_name} уже админ.")
                    return
                add_admin_to_db(target.id)
                current_admins.append(target.id)
                await send_log("appoint_admin", user_id, target.id, "Назначен")
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
                user = await get_user_by_id(uid)
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
            key = parts[2]
            if key != SECRET_KEY:
                await message.channel.send("❌ Неверный ключ.")
                return
            if user_id in current_admins:
                await message.channel.send("✅ Вы уже админ.")
                return
            add_admin_to_db(user_id)
            current_admins.append(user_id)
            await send_log("became_admin", user_id, user_id, "Ключ")
            await message.channel.send("✅ Вы стали админом!")
            return

        # --- статус ---
        if content.lower().startswith("статус"):
            query = content[6:].strip()
            target = await find_user(query) if query else None
            if target:
                if not is_admin(user_id):
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
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ.")
                return
            debtors = get_all_debtors()
            if not debtors:
                await message.channel.send("✅ Никто не должен.")
                return
            lines = ["📋 **Должники:**"]
            for uid, debt in debtors:
                user = await get_user_by_id(uid)
                name = user.display_name if user else f"ID:{uid}"
                lines.append(f"• {name} — {debt:.2f} ч")
            await message.channel.send("\n".join(lines))
            return

        # --- история [@User/ID/имя] [месяцев] ---
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
            target = await find_user(query) if query else None
            if not target:
                await message.channel.send("❌ Укажите пользователя: `история @User/ID/имя [месяцев]`")
                return
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ.")
                return
            cutoff = (now_msk() - td(days=months * 30)).strftime("%Y-%m-%d")
            records = get_full_history(target.id)
            filtered = [
                (date, hours, rtype) for date, hours, rtype in records
                if date >= cutoff or rtype.startswith("⚡")
            ]
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
            target = await find_user(query) if query else None
            if target:
                if not is_admin(user_id):
                    await message.channel.send("⛔ Только админ.")
                    return
                delete_all_user_records(target.id)
                add_history(target.id, "Все записи удалены (увольнение)", f"Кем: {user_id}")
                await send_log("fire", user_id, target.id, "Уволен")
                await message.channel.send(f"🗑️ Все записи {target.display_name} удалены.")
                return
            await message.channel.send("❌ Укажите пользователя: `уволить @User/ID/имя`")
            return

        # --- снять ---
        if content.lower().startswith("снять"):
            query = content[5:].strip()
            target = await find_user(query) if query else None
            if target:
                if not is_admin(user_id):
                    await message.channel.send("⛔ Только админ.")
                    return
                if target.id in SUPER_ADMIN_IDS:
                    await message.channel.send("⛔ Нельзя снять суперадмина.")
                    return
                if target.id in current_admins:
                    remove_admin_from_db(target.id)
                    current_admins.remove(target.id)
                    await send_log("demote", user_id, target.id, "Снят")
                    await message.channel.send(f"✅ {target.display_name} снят с админов.")
                else:
                    await message.channel.send(f"❌ {target.display_name} не админ.")
                return
            await message.channel.send("❌ Укажите пользователя: `снять @User/ID/имя`")
            return

        # --- отчёт [@User/ID/имя] [месяцев] ---
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
            target = await find_user(query) if query else None
            if not target:
                await message.channel.send("❌ Укажите пользователя: `отчёт @User/ID/имя [месяцев]`")
                return
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ.")
                return
            filename, csv_bytes = export_user_csv(target.id, months)
            file = discord.File(io.BytesIO(csv_bytes), filename=filename)
            await message.channel.send(f"📁 Отчёт для {target.display_name} ({months} мес.):", file=file)
            return

        # --- обнулить ---
        if content.lower() == "обнулить":
            if not is_admin(user_id):
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
                        user = await get_user_by_id(uid)
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
            await send_log("clear_overtimes", user_id, None, f"Обнулено: {len(report)} чел, {total:.2f} ч")
            await message.channel.send("\n".join(lines))
            return

        # --- Подсказка ---
        if is_admin(user_id):
            await message.channel.send(
                "**📋 Команды:**\n"
                "• `статус` / `статус @User/ID/имя`\n"
                "• `должники`\n"
                "• `история @User/ID/имя [месяцев]`\n"
                "• `уволить @User/ID/имя`\n"
                "• `снять @User/ID/имя`\n"
                "• `отчёт @User/ID/имя [месяцев]`\n"
                "• `new admin @User/ID/имя`\n"
                "• `обнулить`\n\n"
                "🔸 Пропуски/отработки: общий канал `@Crm_Bot`"
            )
        else:
            await message.channel.send(
                "**📋 Команды:**\n"
                "• `статус` — ваша сводка\n\n"
                "🔸 Пропуски/отработки: общий канал `@Crm_Bot`"
            )
        return

    # ============================================================
    # ОБЩИЙ КАНАЛ
    # ============================================================

    if message.channel.id != GENERAL_CHANNEL_ID:
        return

    if bot.user not in message.mentions:
        return

    clean = content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
    parts = clean.split()
    if not parts:
        await message.add_reaction("❌")
        await message.reply("🤔 Укажите команду. Например: `@Crm_Bot пропуск 4` или `@Crm_Bot пропуск 05.05.2026 4`")
        return

    command = parts[0].lower()

    # --- пропуск ---
    if command == "пропуск":
        if len(parts) < 2:
            await message.add_reaction("❌")
            await message.reply(f"❌ Формат: `@Crm_Bot пропуск Ч` или `@Crm_Bot пропуск ДД.ММ.ГГГГ Ч`")
            return
        date = None
        hours_str = None
        if len(parts) >= 3:
            date = parse_date(parts[1])
            hours_str = parts[2] if date else parts[1]
            if not date:
                date = today_msk()
        else:
            date = today_msk()
            hours_str = parts[1]
        try:
            hours = float(hours_str)
        except ValueError:
            await message.add_reaction("❌")
            await message.reply("❌ Часы должны быть числом (например 2.5)")
            return
        if hours <= 0:
            await message.add_reaction("❌")
            await message.reply("❌ Часы должны быть положительным числом.")
            return
        current = get_hours_for_date(user_id, date, "absences")
        if current + hours > MAX_ABSENCE_PER_DAY:
            await message.add_reaction("❌")
            await message.reply(
                f"❌ Не более {MAX_ABSENCE_PER_DAY} часов пропуска в день. "
                f"Уже записано: {current:.2f} ч, вы запросили: {hours:.2f} ч."
            )
            return
        add_absence(user_id, date, hours)
        await send_log("add_absence", user_id, user_id, f"date={date}, hours={hours}")
        await message.add_reaction("✅")
        return

    # --- отработка ---
    if command == "отработка":
        if len(parts) < 2:
            await message.add_reaction("❌")
            await message.reply(f"❌ Формат: `@Crm_Bot отработка Ч` или `@Crm_Bot отработка ДД.ММ.ГГГГ Ч`")
            return
        date = None
        hours_str = None
        if len(parts) >= 3:
            date = parse_date(parts[1])
            hours_str = parts[2] if date else parts[1]
            if not date:
                date = today_msk()
        else:
            date = today_msk()
            hours_str = parts[1]
        try:
            hours = float(hours_str)
        except ValueError:
            await message.add_reaction("❌")
            await message.reply("❌ Часы должны быть числом (например 2.5)")
            return
        if hours <= 0:
            await message.add_reaction("❌")
            await message.reply("❌ Часы должны быть положительным числом.")
            return
        current = get_hours_for_date(user_id, date, "overtimes")
        if current + hours > MAX_OVERTIME_PER_DAY:
            await message.add_reaction("❌")
            await message.reply(
                f"❌ Не более {MAX_OVERTIME_PER_DAY} часов отработки в день. "
                f"Уже записано: {current:.2f} ч, вы запросили: {hours:.2f} ч."
            )
            return
        add_overtime(user_id, date, hours)
        await send_log("add_overtime", user_id, user_id, f"date={date}, hours={hours}")
        await message.add_reaction("✅")
        return

    # --- удалить ---
    if command == "удалить":
        if len(parts) < 3:
            await message.add_reaction("❌")
            await message.reply(
                "❌ Формат: `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ` или "
                "`@Crm_Bot удалить отработка ДД.ММ.ГГГГ @User` (админ)"
            )
            return
        rtype = parts[1].lower()
        date = parts[2]
        if not is_valid_date(date):
            await message.add_reaction("❌")
            await message.reply("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ, например: 31.12.2026")
            return
        target_mention = None
        for m in message.mentions:
            if m.id != bot.user.id:
                target_mention = m
                break
        if is_admin(user_id) and target_mention:
            target_id = target_mention.id
            target_name = target_mention.display_name
        else:
            target_id = user_id
            target_name = message.author.display_name
        if rtype == "пропуск":
            deleted = delete_absence(target_id, date)
        elif rtype == "отработка":
            deleted = delete_overtime(target_id, date)
        else:
            await message.add_reaction("❌")
            await message.reply("❌ Укажите тип: `пропуск` или `отработка`")
            return
        if deleted:
            add_history(target_id, f"Удалён {rtype} за {date}", f"Кем: {user_id}")
            await send_log(f"delete_{rtype}", user_id, target_id, f"date={date}")
            await message.add_reaction("✅")
        else:
            await message.add_reaction("❌")
            await message.reply(f"❌ Не нашёл {rtype} за {date} у {target_name}")
        return

    # --- Подсказка ---
    await message.add_reaction("ℹ️")
    await message.reply(
        "**📋 Шаблоны команд:**\n"
        f"• `@Crm_Bot пропуск Ч` — пропуск на сегодня (макс {MAX_ABSENCE_PER_DAY} ч/день)\n"
        f"• `@Crm_Bot пропуск ДД.ММ.ГГГГ Ч` — пропуск на дату\n"
        f"• `@Crm_Bot пропуск сегодня/вчера/завтра Ч` — пропуск словами\n"
        f"• `@Crm_Bot отработка Ч` — отработка на сегодня (макс {MAX_OVERTIME_PER_DAY} ч/день)\n"
        f"• `@Crm_Bot отработка ДД.ММ.ГГГГ Ч` — отработка на дату\n"
        f"• `@Crm_Bot отработка сегодня/вчера/завтра Ч` — отработка словами\n"
        "• `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ` — удалить свой пропуск\n"
        "• `@Crm_Bot удалить отработка ДД.ММ.ГГГГ` — удалить свою отработку\n\n"
        "🔹 Админ: `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ @User`"
    )


# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == "__main__":
    print("🚀 Запускаю Crm_Bot...")
    bot.run(TOKEN)