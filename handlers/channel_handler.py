# ============================================================
# handlers/channel_handler.py — обработка команд общего канала
# ============================================================

from .utils import is_valid_date, parse_date, today_msk, is_admin, send_log
from config import MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY
from db import (
    add_absence, add_overtime, add_history,
    delete_absence, delete_overtime,
    get_hours_for_date
)


async def handle_channel(message, bot, current_admins: list):
    content = message.content.strip()
    user_id = message.author.id

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
        await send_log("add_absence", user_id, user_id, f"date={date}, hours={hours}", bot)
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
        await send_log("add_overtime", user_id, user_id, f"date={date}, hours={hours}", bot)
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
        if is_admin(user_id, current_admins) and target_mention:
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
            await send_log(f"delete_{rtype}", user_id, target_id, f"date={date}", bot)
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