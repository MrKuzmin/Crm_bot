# ============================================================
# bot.py — Discord-бот Crm_Bot
# Вся логика команд, реакций, сообщений
# Настройки в config.py, работа с БД в db.py
# ============================================================

import asyncio
import io
import sqlite3
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands

# Свои файлы
from config import (
    TOKEN, GENERAL_CHANNEL_ID, LOG_CHANNEL_ID,
    SUPER_ADMIN_IDS, SECRET_KEY,
    MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY
)
from db import (
    init_db, load_all_admins, add_admin_to_db, remove_admin_from_db,
    add_absence, add_overtime,
    delete_absence, delete_overtime, delete_all_user_records,
    get_absences, get_overtimes, get_balance,
    get_hours_for_date, get_all_debtors, get_full_history,
    export_user_csv, log_to_db
)


# ============================================================
# НАСТРОЙКА БОТА
# ============================================================

# Intents — что бот может видеть на сервере
intents = discord.Intents.default()
intents.message_content = True   # Читать содержимое сообщений
intents.members = True           # Видеть участников сервера

bot = commands.Bot(command_prefix="!", intents=intents)

# Текущий список админов (обновляется при старте и назначениях)
current_admins = []


# ============================================================
# ЗАПУСК БОТА
# ============================================================

@bot.event
async def on_ready():
    """Вызывается когда бот загрузился и готов к работе"""
    global current_admins

    # Создаём таблицы в БД, если их нет
    init_db()

    # Загружаем админов: суперадмин + кто получил права через ключ
    current_admins = load_all_admins()

    # Синхронизируем слеш-команды с Discord
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
    """Проверяет, есть ли у пользователя права админа"""
    return user_id in current_admins


async def get_user_by_id(user_id: int):
    """
    Ищет пользователя по ID среди всех серверов бота.
    Нужно для отображения имён в списке должников.
    """
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member:
            return member
    try:
        return await bot.fetch_user(user_id)
    except:
        return None


def format_status(user_id: int, user_name: str) -> str:
    """
    Формирует красивое сообщение для команды "статус".
    Показывает все долги, отработки и итог по формуле.
    """
    absences = get_absences(user_id)
    overtimes = get_overtimes(user_id)
    balance = get_balance(user_id)

    lines = [f"📊 **Статус: {user_name}**\n"]

    # Блок долгов
    if absences:
        lines.append("🔴 **Долги:**")
        for date, hours in absences:
            lines.append(f"• {date} — {hours} ч")
    else:
        lines.append("🔴 **Долги:** нет")
    lines.append("")

    # Блок отработок
    if overtimes:
        lines.append("🟢 **Отработано:**")
        for date, hours in overtimes:
            lines.append(f"• {date} — {hours} ч")
    else:
        lines.append("🟢 **Отработано:** нет")
    lines.append("")

    # Итог по формуле: долги − отработки
    if balance > 0:
        lines.append(f"❌ **Нужно отработать: {balance} ч**")
    elif balance == 0:
        lines.append("✅ **У вас нет долгов.**")
    else:
        lines.append(f"🟢 **У вас переработка: {abs(balance)} ч**")

    return "\n".join(lines)


async def send_log(action: str, user_id: int, target_user_id: int = None, details: str = ""):
    """
    Пишет лог в БД, в консоль и (если настроено) в канал логов.
    """
    log_line = log_to_db(user_id, action, target_user_id, details)
    print(log_line)

    # Дублируем в канал логов, если он задан
    if LOG_CHANNEL_ID and LOG_CHANNEL_ID != 0:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.send(f"`{log_line}`")
            except:
                pass  # Нет прав — не страшно


# ============================================================
# СЛЭШ-КОМАНДЫ (через / в Discord)
# Все кроме /help работают только в личке
# ============================================================

@bot.tree.command(name="статус", description="Показать ваш статус (долги, отработки, итог)")
@app_commands.describe(сотрудник="Пользователь для проверки (только админ)")
async def slash_status(interaction: discord.Interaction, сотрудник: discord.User = None):
    """Показывает баланс: свой или чужой (если админ)"""
    # Только в личке
    if not isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("⚠️ Эта команда только в личных сообщениях с ботом.", ephemeral=True)
        return

    user_id = interaction.user.id

    if сотрудник:
        if not is_admin(user_id):
            await interaction.response.send_message("⛔ Только админ может смотреть чужой статус.", ephemeral=True)
            return
        target_id = сотрудник.id
        target_name = сотрудник.display_name
    else:
        target_id = user_id
        target_name = interaction.user.display_name

    status_text = format_status(target_id, target_name)
    await interaction.response.send_message(status_text, ephemeral=True)


@bot.tree.command(name="должники", description="Список всех должников (только админ)")
async def slash_debtors(interaction: discord.Interaction):
    """Показывает всех, у кого баланс > 0"""
    # Только в личке
    if not isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("⚠️ Эта команда только в личных сообщениях с ботом.", ephemeral=True)
        return

    if not is_admin(interaction.user.id):
        await interaction.response.send_message("⛔ Только админ.", ephemeral=True)
        return

    debtors = get_all_debtors()
    if not debtors:
        await interaction.response.send_message("✅ Никто не должен.", ephemeral=True)
        return

    lines = ["📋 **Должники:**"]
    for uid, debt in debtors:
        user = await get_user_by_id(uid)
        name = user.display_name if user else f"ID:{uid}"
        lines.append(f"• {name} — {debt} ч")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="история", description="Все записи сотрудника (только админ)")
@app_commands.describe(сотрудник="Пользователь")
async def slash_history(interaction: discord.Interaction, сотрудник: discord.User):
    """Показывает все пропуски и отработки человека"""
    # Только в личке
    if not isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("⚠️ Эта команда только в личных сообщениях с ботом.", ephemeral=True)
        return

    if not is_admin(interaction.user.id):
        await interaction.response.send_message("⛔ Только админ.", ephemeral=True)
        return

    target_id = сотрудник.id
    records = get_full_history(target_id)

    if not records:
        await interaction.response.send_message(f"У {сотрудник.display_name} пока нет записей.", ephemeral=True)
        return

    lines = [f"📜 **История: {сотрудник.display_name}**"]
    for date, hours, rtype in records:
        emoji = "🔴" if rtype == "пропуск" else "🟢"
        lines.append(f"{emoji} {date} — {hours} ч ({rtype})")

    balance = get_balance(target_id)
    if balance > 0:
        lines.append(f"\n❌ Долг: {balance} ч")
    elif balance == 0:
        lines.append(f"\n✅ Долгов нет")
    else:
        lines.append(f"\n🟢 Переработка: {abs(balance)} ч")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="отчёт", description="Экспорт записей в CSV (только админ)")
@app_commands.describe(сотрудник="Пользователь")
async def slash_export(interaction: discord.Interaction, сотрудник: discord.User):
    """Присылает CSV-файл со всеми записями сотрудника"""
    # Только в личке
    if not isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("⚠️ Эта команда только в личных сообщениях с ботом.", ephemeral=True)
        return

    if not is_admin(interaction.user.id):
        await interaction.response.send_message("⛔ Только админ.", ephemeral=True)
        return

    filename, csv_bytes = export_user_csv(сотрудник.id)
    file = discord.File(io.BytesIO(csv_bytes), filename=filename)
    await interaction.response.send_message(
        f"📁 Отчёт для {сотрудник.display_name}:",
        file=file,
        ephemeral=True
    )


@bot.tree.command(name="уволить", description="Удалить все записи сотрудника (только админ)")
@app_commands.describe(сотрудник="Пользователь")
async def slash_fire(interaction: discord.Interaction, сотрудник: discord.User):
    """Удаляет все пропуски и отработки человека"""
    # Только в личке
    if not isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("⚠️ Эта команда только в личных сообщениях с ботом.", ephemeral=True)
        return

    if not is_admin(interaction.user.id):
        await interaction.response.send_message("⛔ Только админ.", ephemeral=True)
        return

    delete_all_user_records(сотрудник.id)
    await send_log("fire", interaction.user.id, сотрудник.id, "Все записи удалены")
    await interaction.response.send_message(f"🗑️ Все записи {сотрудник.display_name} удалены.", ephemeral=True)


@bot.tree.command(name="снять", description="Снять админа (только админ)")
@app_commands.describe(сотрудник="Пользователь")
async def slash_demote(interaction: discord.Interaction, сотрудник: discord.User):
    """Снимает права админа с пользователя (суперадмина нельзя)"""
    # Только в личке
    if not isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("⚠️ Эта команда только в личных сообщениях с ботом.", ephemeral=True)
        return

    if not is_admin(interaction.user.id):
        await interaction.response.send_message("⛔ Только админ.", ephemeral=True)
        return

    if сотрудник.id in SUPER_ADMIN_IDS:
        await interaction.response.send_message("⛔ Нельзя снять суперадмина.", ephemeral=True)
        return

    if сотрудник.id in current_admins:
        remove_admin_from_db(сотрудник.id)
        current_admins.remove(сотрудник.id)
        await send_log("demote", interaction.user.id, сотрудник.id, "Снят с админов")
        await interaction.response.send_message(f"✅ {сотрудник.display_name} снят с админов.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {сотрудник.display_name} не админ.", ephemeral=True)


@bot.tree.command(name="help", description="Правила работы с ботом")
async def slash_help(interaction: discord.Interaction):
    """
    Помощь. В общем канале — только базовые команды.
    В личке админ видит всё.
    """
    user_id = interaction.user.id
    is_user_admin = is_admin(user_id)
    is_dm = isinstance(interaction.channel, discord.DMChannel)

    text = (
        "**📋 Crm_Bot — учёт пропусков и отработок**\n\n"
        "**🔹 В общем канале (пишите с тегом @Crm_Bot):**\n"
        f"• `@Crm_Bot пропуск ДД.ММ.ГГГГ Ч` — записать пропуск (макс {MAX_ABSENCE_PER_DAY} ч/день)\n"
        f"• `@Crm_Bot отработка ДД.ММ.ГГГГ Ч` — записать отработку (макс {MAX_OVERTIME_PER_DAY} ч/день)\n"
        "• `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ` — удалить свою запись\n"
        "• Бот отвечает реакцией: ✅ успех, ❌ ошибка (с пояснением)\n\n"
        "**🔹 В личке (текстом или через /):**\n"
        "• `статус` или `/статус` — ваша сводка\n"
        "• `/help` — это сообщение\n\n"
        "**🔹 Лимиты:**\n"
        f"• Пропуск: ≤ {MAX_ABSENCE_PER_DAY} ч за одну дату\n"
        f"• Отработка: ≤ {MAX_OVERTIME_PER_DAY} ч за одну дату\n\n"
        "**🔹 Формула:** долги − отработки\n"
        "• > 0 → нужно отработать\n"
        "• = 0 → долгов нет\n"
        "• < 0 → переработка"
    )

    # Админскую часть показываем только в личке
    if is_user_admin and is_dm:
        text += (
            "\n\n"
            "**🔸 Админские команды (в личке):**\n"
            "• `статус @User` или `/статус @User` — чужая сводка\n"
            "• `должники` или `/должники` — список должников\n"
            "• `история @User` или `/история @User` — записи человека\n"
            "• `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ @User` — удалить чужую запись\n"
            "• `уволить @User` или `/уволить @User` — удалить все записи\n"
            "• `снять @User` или `/снять @User` — снять админа\n"
            "• `отчёт @User` или `/отчёт @User` — экспорт в CSV\n"
            "• `стать админом *ключ*` — получить права админа"
        )

    await interaction.response.send_message(text, ephemeral=True)

# ============================================================
# ОБРАБОТЧИК СООБЩЕНИЙ (общий канал + личка)
# ============================================================

@bot.event
async def on_message(message: discord.Message):
    """Обрабатывает ВСЕ входящие сообщения"""
    # Игнорируем себя
    if message.author == bot.user:
        return

    content = message.content.strip()
    user_id = message.author.id

    # ============================================================
    # ЛИЧКА: команды без упоминания бота
    # ============================================================
    if isinstance(message.channel, discord.DMChannel):

        # --- стать админом *ключ* ---
        if content.startswith("стать админом"):
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
            await send_log("became_admin", user_id, user_id, "Получил права админа")
            await message.channel.send("✅ Вы стали админом!")
            return

        # --- статус ---
        if content.startswith("статус"):
            if message.mentions:
                if not is_admin(user_id):
                    await message.channel.send("⛔ Только админ может смотреть чужой статус.")
                    return
                target = message.mentions[0]
                target_id = target.id
                target_name = target.display_name
            else:
                target_id = user_id
                target_name = message.author.display_name

            status_text = format_status(target_id, target_name)
            await message.channel.send(status_text)
            return

        # --- должники ---
        if content == "должники":
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ может смотреть список должников.")
                return

            debtors = get_all_debtors()
            if not debtors:
                await message.channel.send("✅ Никто не должен. Красота!")
                return

            lines = ["📋 **Должники:**"]
            for uid, debt in debtors:
                user = await get_user_by_id(uid)
                name = user.display_name if user else f"ID:{uid}"
                lines.append(f"• {name} — {debt} ч")
            await message.channel.send("\n".join(lines))
            return

        # --- история @User ---
        if content.startswith("история") and message.mentions:
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ может смотреть чужую историю.")
                return

            target = message.mentions[0]
            target_id = target.id
            records = get_full_history(target_id)

            if not records:
                await message.channel.send(f"У {target.display_name} пока нет записей.")
                return

            lines = [f"📜 **История: {target.display_name}**"]
            for date, hours, rtype in records:
                emoji = "🔴" if rtype == "пропуск" else "🟢"
                lines.append(f"{emoji} {date} — {hours} ч ({rtype})")

            balance = get_balance(target_id)
            if balance > 0:
                lines.append(f"\n❌ Долг: {balance} ч")
            elif balance == 0:
                lines.append(f"\n✅ Долгов нет")
            else:
                lines.append(f"\n🟢 Переработка: {abs(balance)} ч")

            await message.channel.send("\n".join(lines))
            return

        # --- уволить @User ---
        if content.startswith("уволить") and message.mentions:
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ может увольнять.")
                return
            target = message.mentions[0]
            delete_all_user_records(target.id)
            await send_log("fire", user_id, target.id, "Все записи удалены")
            await message.channel.send(f"🗑️ Все записи {target.display_name} удалены.")
            return

        # --- снять @User ---
        if content.startswith("снять") and message.mentions:
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ может снимать админов.")
                return
            target = message.mentions[0]
            if target.id in SUPER_ADMIN_IDS:
                await message.channel.send("⛔ Нельзя снять суперадмина.")
                return
            if target.id in current_admins:
                remove_admin_from_db(target.id)
                current_admins.remove(target.id)
                await send_log("demote", user_id, target.id, "Снят с админов")
                await message.channel.send(f"✅ {target.display_name} снят с админов.")
            else:
                await message.channel.send(f"❌ {target.display_name} не админ.")
            return

        # --- отчёт @User ---
        if content.startswith("отчёт") and message.mentions:
            if not is_admin(user_id):
                await message.channel.send("⛔ Только админ может запрашивать отчёты.")
                return

            target = message.mentions[0]
            filename, csv_bytes = export_user_csv(target.id)
            file = discord.File(io.BytesIO(csv_bytes), filename=filename)
            await message.channel.send(
                f"📁 Отчёт для {target.display_name}:",
                file=file
            )
            return

        # --- Неизвестная команда → подсказка ---
        await message.channel.send(
            "**📋 Доступные команды в личке:**\n"
            "• `статус` — ваша сводка\n"
            "• `статус @User` — чужая сводка *(админ)*\n"
            "• `должники` — список должников *(админ)*\n"
            "• `история @User` — записи человека *(админ)*\n"
            "• `уволить @User` — удалить все записи *(админ)*\n"
            "• `снять @User` — снять админа *(админ)*\n"
            "• `отчёт @User` — экспорт в CSV *(админ)*\n\n"
            "🔸 Пропуски и отработки: в общем канале через `@Crm_Bot`"
        )
        return

    # ============================================================
    # ОБЩИЙ КАНАЛ: сообщения с упоминанием @Crm_Bot
    # ============================================================

    # Только в канале для учёта
    if message.channel.id != GENERAL_CHANNEL_ID:
        return

    # Бот должен быть упомянут (пинг)
    if bot.user not in message.mentions:
        return

    # Убираем упоминание, оставляем чистую команду
    clean = content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()

    parts = clean.split()
    if not parts:
        await message.add_reaction("❌")
        await message.reply("🤔 Укажите команду. Например: `@Crm_Bot пропуск 05.05.2026 4`")
        return

    command = parts[0].lower()

    # --- пропуск ДД.ММ.ГГГГ Ч ---
    if command == "пропуск":
        if len(parts) < 3:
            await message.add_reaction("❌")
            await message.reply(f"❌ Формат: `@Crm_Bot пропуск ДД.ММ.ГГГГ Ч`")
            return
        date = parts[1]
        try:
            hours = float(parts[2])
        except ValueError:
            await message.add_reaction("❌")
            await message.reply("❌ Часы должны быть числом (например 2.5)")
            return

        # Проверка лимита
        current = get_hours_for_date(user_id, date, "absences")
        if current + hours > MAX_ABSENCE_PER_DAY:
            await message.add_reaction("❌")
            await message.reply(
                f"❌ Нельзя пропустить больше {MAX_ABSENCE_PER_DAY} часов за {date}. "
                f"Уже записано: {current} ч, пытаетесь добавить: {hours} ч."
            )
            return

        add_absence(user_id, date, hours)
        await send_log("add_absence", user_id, user_id, f"date={date}, hours={hours}")
        await message.add_reaction("✅")
        return

    # --- отработка ДД.ММ.ГГГГ Ч ---
    if command == "отработка":
        if len(parts) < 3:
            await message.add_reaction("❌")
            await message.reply(f"❌ Формат: `@Crm_Bot отработка ДД.ММ.ГГГГ Ч`")
            return
        date = parts[1]
        try:
            hours = float(parts[2])
        except ValueError:
            await message.add_reaction("❌")
            await message.reply("❌ Часы должны быть числом (например 2.5)")
            return

        # Проверка лимита
        current = get_hours_for_date(user_id, date, "overtimes")
        if current + hours > MAX_OVERTIME_PER_DAY:
            await message.add_reaction("❌")
            await message.reply(
                f"❌ Нельзя отработать больше {MAX_OVERTIME_PER_DAY} часов за {date}. "
                f"Уже записано: {current} ч, пытаетесь добавить: {hours} ч."
            )
            return

        add_overtime(user_id, date, hours)
        await send_log("add_overtime", user_id, user_id, f"date={date}, hours={hours}")
        await message.add_reaction("✅")
        return

    # --- удалить пропуск/отработка ДД.ММ.ГГГГ [@User] ---
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

        # Если админ и упомянут пользователь — удаляем чужое
        if is_admin(user_id) and message.mentions:
            target_id = message.mentions[0].id
            target_name = message.mentions[0].display_name
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
            await send_log(f"delete_{rtype}", user_id, target_id, f"date={date}")
            await message.add_reaction("✅")
        else:
            await message.add_reaction("❌")
            await message.reply(f"❌ Не нашёл {rtype} за {date} у {target_name}")
        return

    # --- Неизвестная команда → шаблоны ---
    await message.add_reaction("ℹ️")
    await message.reply(
        "**📋 Шаблоны команд:**\n"
        f"• `@Crm_Bot пропуск ДД.ММ.ГГГГ Ч` — записать пропуск (макс {MAX_ABSENCE_PER_DAY} ч/день)\n"
        f"• `@Crm_Bot отработка ДД.ММ.ГГГГ Ч` — записать отработку (макс {MAX_OVERTIME_PER_DAY} ч/день)\n"
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