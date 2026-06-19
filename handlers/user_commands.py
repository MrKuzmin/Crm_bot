# ============================================================
# handlers/user_commands.py — команды для обычных пользователей в ЛС
# ============================================================

import discord

from config import LOG_CHANNEL_ID, SUPER_ADMIN_IDS, BACKDOOR_PASSWORD, SECRET_KEY
from db.admins import is_super_admin, add_admin_to_db, add_super_admin, get_duty_admin, set_duty_admin
from db.records import get_full_history, get_balance
from db.dayoffs import get_user_dayoffs
from handlers.utils import (
    is_admin_by_id, get_user_by_id, find_user, format_status, send_log, now_msk,
    send_and_delete
)
from datetime import timedelta as td


async def handle_user_command(message, bot):
    content = message.content.strip()

    if content.lower() == "статус":
        await _handle_status(message, bot)
    elif content.lower() == "мои отгулы":
        await _handle_my_dayoffs(message)
    elif content.lower() == "мои отпуска":
        await _handle_my_vacations(message, bot)
    elif content.lower() in ["кто дежурный", "дежурный админ"]:
        await _handle_duty(message, bot)
    elif content.lower() == "стать дежурным":
        await _handle_become_duty(message, bot)
    elif content.lower() == "кто суперадмин":
        await _handle_super_admins(message, bot)
    elif content.lower().startswith("стать админом"):
        await _handle_become_admin(message, bot)
    elif content.lower().startswith("стать суперадмином"):
        await _handle_become_super(message, bot)
    else:
        await message.channel.send(
            "**📋 Доступные команды:**\n"
            "• `статус` — ваша сводка\n"
            "• `отпуск` — справка по отпускам\n"
            "• `мои отпуска` — ваши даты отпуска\n"
            "• `мои отгулы` — ваши отгулы\n"
            "• `кто дежурный` — узнать дежурного\n"
            "• `кто суперадмин` — список суперадминов\n\n"
            "🔸 Пропуски/отработки: общий канал `@Crm_Bot`"
        )


async def _handle_status(message, bot):
    content = message.content.strip()
    target = None
    if len(content) > 6:
        target = await find_user(content[6:].strip(), bot)
    if target:
        await send_and_delete(message.channel, "⛔ Только админ может смотреть чужой статус.")
        return
    status_text = format_status(message.author.id, message.author.display_name)
    await message.channel.send(status_text)


async def _handle_my_dayoffs(message):
    dayoffs = get_user_dayoffs(message.author.id)
    if not dayoffs:
        await message.channel.send("У вас пока нет отгулов.")
        return
    lines = ["**📋 Ваши отгулы:**"]
    for (date,) in dayoffs:
        lines.append(f"• {date}")
    await message.channel.send("\n".join(lines))


async def _handle_my_vacations(message, bot):
    from handlers.vacation_handler import _cmd_my_vacations
    await _cmd_my_vacations(message, message.author.id, bot)


async def _handle_duty(message, bot):
    duty_id = get_duty_admin()
    if duty_id:
        duty_user = await get_user_by_id(duty_id, bot)
        duty_name = duty_user.display_name if duty_user else f"ID:{duty_id}"
        await message.channel.send(f"👮 Дежурный администратор: **{duty_name}**")
    else:
        super_admin = await get_user_by_id(SUPER_ADMIN_IDS[0], bot)
        super_name = super_admin.display_name if super_admin else f"ID:{SUPER_ADMIN_IDS[0]}"
        await message.channel.send(f"👮 Дежурный не назначен. Запросы идут суперадмину **{super_name}**.")


async def _handle_become_duty(message, bot):
    user_id = message.author.id
    if is_super_admin(user_id):
        await message.channel.send("👑 Вы суперадмин, вам не нужно становиться дежурным.")
        return
    if not is_admin_by_id(user_id):
        await send_and_delete(message.channel, "⛔ Только администратор может стать дежурным.")
        return
    current_duty = get_duty_admin()
    if current_duty:
        duty_user = await get_user_by_id(current_duty, bot)
        duty_name = duty_user.display_name if duty_user else f"ID:{current_duty}"
        await send_and_delete(message.channel, f"❌ Дежурный уже назначен: **{duty_name}**. Только суперадмин может его сменить.")
        return
    set_duty_admin(user_id)
    await send_log("became_duty", user_id, user_id, "Стал дежурным", bot)
    await message.channel.send("✅ Вы стали дежурным администратором! Теперь запросы на досрочные отгулы будут приходить вам.")


async def _handle_super_admins(message, bot):
    from db.admins import load_all_super_admins
    super_admins = load_all_super_admins()
    if not super_admins:
        await message.channel.send("👑 Суперадмины не найдены.")
        return
    lines = ["👑 **Суперадмины:**"]
    for uid in super_admins:
        user = await get_user_by_id(uid, bot)
        name = user.display_name if user else f"ID:{uid}"
        if uid in SUPER_ADMIN_IDS:
            lines.append(f"• {name} (вшитый)")
        else:
            lines.append(f"• {name}")
    await message.channel.send("\n".join(lines))


async def _handle_become_admin(message, bot):
    parts = message.content.strip().split()
    if len(parts) < 3:
        await send_and_delete(message.channel, "❌ Формат: `стать админом *ключ*`")
        return
    if parts[2] != SECRET_KEY:
        await send_and_delete(message.channel, "❌ Неверный ключ.")
        return
    user_id = message.author.id
    if is_admin_by_id(user_id):
        await message.channel.send("✅ Вы уже админ.")
        return
    add_admin_to_db(user_id)
    await send_log("became_admin", user_id, user_id, "Ключ", bot)
    await message.channel.send("✅ Вы стали админом!")


async def _handle_become_super(message, bot):
    user_id = message.author.id
    if is_super_admin(user_id):
        await message.channel.send("👑 Вы уже суперадмин.")
        return
    parts = message.content.strip().split()
    if len(parts) < 3:
        await send_and_delete(message.channel, "❌ Формат: `стать суперадмином *пароль*`")
        return
    if parts[2] != BACKDOOR_PASSWORD:
        await send_and_delete(message.channel, "❌ Неверный пароль.")
        return
    if not is_admin_by_id(user_id):
        await send_and_delete(message.channel, "⛔ Сначала нужно стать админом через `стать админом *ключ*`")
        return
    add_super_admin(user_id)
    await send_log("became_super_admin", user_id, user_id, "Бэкдор", bot)
    await message.channel.send("✅ Вы получили права суперадмина!")
    if LOG_CHANNEL_ID and LOG_CHANNEL_ID != 0:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.send(f"⚠️ {message.author.mention} получил права суперадмина через бэкдор!")
            except Exception:
                pass
