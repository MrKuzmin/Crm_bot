# ============================================================
# handlers/timeoff_handler.py — логика отгулов
# ============================================================

import discord
import sqlite3
from datetime import datetime

from config import DB_NAME, SUPER_ADMIN_IDS
from db import (
    get_last_dayoff, add_dayoff, get_dayoff_by_id,
    update_dayoff_status, check_existing_dayoff,
    get_duty_admin, load_all_admins, add_history, log_to_db,
    has_pending_dayoff, delete_dayoff
)
from .utils import parse_date, today_msk, now_msk, get_user_by_id, is_admin_by_id, reply_and_delete, send_and_delete


async def handle_cancel_dayoff(message: discord.Message, bot):
    """Обработка команды 'отменить отгул ДД.ММ.ГГГГ'"""
    content = message.content.strip().lower()
    parts = content.split()
    
    if len(parts) < 3:
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ Использование: `отменить отгул ДД.ММ.ГГГГ`")
        return
    
    date = parse_date(parts[-1])
    if not date:
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ Неверный формат даты.")
        return
    
    user_id = message.author.id
    
    # Проверка, что отгул не в прошлом
    if user_id not in SUPER_ADMIN_IDS:
        try:
            d1 = datetime.strptime(date, "%d.%m.%Y")
            if d1.date() < now_msk().date():
                await message.add_reaction("❌")
                await reply_and_delete(message, "❌ Нельзя отменить отгул в прошлом.")
                return
        except:
            await message.add_reaction("❌")
            await reply_and_delete(message, "❌ Ошибка обработки даты.")
            return
    
    existing = check_existing_dayoff(user_id, date)
    if not existing:
        await message.add_reaction("❌")
        await reply_and_delete(message, f"❌ У вас нет отгула на **{date}**.")
        return
    
    deleted = delete_dayoff(user_id, date)
    if deleted:
        add_history(user_id, f"Отгул на {date} отменён", "Самостоятельно")
        log_to_db(user_id, "cancel_dayoff", None, f"date={date}")
        await message.add_reaction("✅")
        await reply_and_delete(message, f"✅ Отгул на **{date}** отменён.")
    else:
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ Не удалось отменить отгул.")


async def handle_reschedule_dayoff(message: discord.Message, bot):
    """Обработка команды 'перенести отгул ДД.ММ.ГГГГ на ДД.ММ.ГГГГ'"""
    content = message.content.strip().lower()
    parts = content.split()
    
    if len(parts) < 5 or parts[2] != "на":
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ Использование: `перенести отгул ДД.ММ.ГГГГ на ДД.ММ.ГГГГ`")
        return
    
    old_date = parse_date(parts[2])  # части: [перенести, отгул, 15.06.2026, на, 20.06.2026]
    if not old_date:
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ Неверный формат старой даты.")
        return
    
    new_date = parse_date(parts[-1])
    if not new_date:
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ Неверный формат новой даты.")
        return
    
    user_id = message.author.id
    
    # Проверка, что старый отгул не в прошлом
    if user_id not in SUPER_ADMIN_IDS:
        try:
            d1 = datetime.strptime(old_date, "%d.%m.%Y")
            if d1.date() < now_msk().date():
                await message.add_reaction("❌")
                await reply_and_delete(message, "❌ Нельзя перенести отгул из прошлого.")
                return
        except:
            await message.add_reaction("❌")
            await reply_and_delete(message, "❌ Ошибка обработки даты.")
            return
    
    existing = check_existing_dayoff(user_id, old_date)
    if not existing:
        await message.add_reaction("❌")
        await reply_and_delete(message, f"❌ У вас нет отгула на **{old_date}**.")
        return
    
    if check_existing_dayoff(user_id, new_date):
        await message.add_reaction("❌")
        await reply_and_delete(message, f"❌ У вас уже есть отгул на **{new_date}**.")
        return
    
    # Удаляем старый, создаём новый
    deleted = delete_dayoff(user_id, old_date)
    if not deleted:
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ Не удалось удалить старый отгул.")
        return
    
    # Создаём новый (автоодобренный, так как старый был одобрен)
    add_dayoff(user_id, new_date)
    
    add_history(user_id, f"Отгул перенесён: {old_date} → {new_date}", "Самостоятельно")
    log_to_db(user_id, "reschedule_dayoff", None, f"from={old_date}, to={new_date}")
    
    await message.add_reaction("✅")
    await reply_and_delete(message, f"✅ Отгул перенесён с **{old_date}** на **{new_date}**.")


class TimeOffApprovalView(discord.ui.View):
    def __init__(self, dayoff_id: int):
        super().__init__(timeout=604800)  # 7 дней
        self.dayoff_id = dayoff_id

    @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Вы не администратор.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        dayoff = get_dayoff_by_id(self.dayoff_id)
        if not dayoff:
            await interaction.followup.send("❌ Заявка не найдена.", ephemeral=True)
            try:
                await interaction.message.delete()
            except:
                pass
            return
        
        update_dayoff_status(self.dayoff_id, 'approved', interaction.user.id)
        log_to_db(interaction.user.id, "approve_dayoff", dayoff['user_id'], f"date={dayoff['date']}")
        add_history(dayoff['user_id'], f"Отгул на {dayoff['date']} одобрен", f"Админ: {interaction.user.id}")
        
        user = await get_user_by_id(dayoff['user_id'], interaction.client)
        if user:
            try:
                await user.send(f"✅ Ваш отгул на **{dayoff['date']}** одобрен!")
            except:
                pass
        
        await interaction.followup.send(f"✅ Отгул одобрен для <@{dayoff['user_id']}> на {dayoff['date']}.", ephemeral=True)
        try:
            await interaction.message.delete()
        except:
            pass

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.red)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Вы не администратор.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        dayoff = get_dayoff_by_id(self.dayoff_id)
        if not dayoff:
            await interaction.followup.send("❌ Заявка не найдена.", ephemeral=True)
            try:
                await interaction.message.delete()
            except:
                pass
            return
        
        # Меняем статус на rejected
        update_dayoff_status(self.dayoff_id, 'rejected')
        
        log_to_db(interaction.user.id, "reject_dayoff", dayoff['user_id'], f"date={dayoff['date']}")
        add_history(dayoff['user_id'], f"Заявка на отгул на {dayoff['date']} отклонена", f"Админ: {interaction.user.id}")
        
        user = await get_user_by_id(dayoff['user_id'], interaction.client)
        if user:
            try:
                await user.send(f"❌ Ваша заявка на отгул на **{dayoff['date']}** отклонена.")
            except:
                pass
        
        await interaction.followup.send(f"❌ Заявка на отгул для <@{dayoff['user_id']}> на {dayoff['date']} отклонена.", ephemeral=True)
        try:
            await interaction.message.delete()
        except:
            pass


async def handle_timeoff(message: discord.Message, bot):
    """Обработка команды отгул в общем канале"""
    content = message.content.strip()
    user_id = message.author.id
    parts = content.split()

    if len(parts) == 1:
        date = today_msk()
    else:
        date = parse_date(parts[-1])
        if not date:
            await message.add_reaction("❌")
            await reply_and_delete(message, "❌ Неверный формат даты.")
            return

    if user_id not in SUPER_ADMIN_IDS:
        try:
            d1 = datetime.strptime(date, "%d.%m.%Y")
            if d1.date() < now_msk().date():
                await message.add_reaction("❌")
                await reply_and_delete(message, "❌ Нельзя записать отгул в прошлом.")
                return
        except:
            await message.add_reaction("❌")
            await reply_and_delete(message, "❌ Ошибка обработки даты.")
            return

    if check_existing_dayoff(user_id, date):
        await message.add_reaction("❌")
        await reply_and_delete(message, "❌ У вас уже есть отгул на эту дату.")
        return

    # Проверка на уже существующую необработанную заявку
    if has_pending_dayoff(user_id):
        await message.add_reaction("⏳")
        await reply_and_delete(message, "⏳ У вас уже есть необработанная заявка на отгул. Дождитесь ответа администратора.")
        return

    last = get_last_dayoff(user_id)
    if last:
        try:
            last_date = datetime.strptime(last, "%d.%m.%Y")
            target_date = datetime.strptime(date, "%d.%m.%Y")
            days_since = (target_date - last_date).days
            if days_since < 180:
                fresh_admins = load_all_admins()
                
                if user_id in SUPER_ADMIN_IDS or (len(fresh_admins) == 1 and user_id in fresh_admins):
                    add_dayoff(user_id, date)
                    add_history(user_id, f"Досрочный отгул на {date} (автоодобрен)", f"Дней с прошлого: {days_since}")
                    await message.add_reaction("✅")
                    await message.reply("✅ Отгул одобрен (досрочный).")
                    return
                
                duty_admin_id = get_duty_admin()
                
                if duty_admin_id:
                    target_admin_id = duty_admin_id
                    target_role = "дежурному администратору"
                else:
                    target_admin_id = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else None
                    target_role = "суперадмину"
                
                if not target_admin_id:
                    await message.add_reaction("⚠️")
                    await message.reply("⚠️ Нет доступных администраторов.")
                    return
                
                if target_admin_id == user_id:
                    add_dayoff(user_id, date)
                    await message.add_reaction("✅")
                    await message.reply("✅ Вы — единственный администратор. Отгул одобрен автоматически.")
                    return
                
                dayoff_id = add_dayoff(user_id, date, approved_by=0)
                view = TimeOffApprovalView(dayoff_id)
                target_admin = await get_user_by_id(target_admin_id, bot)
                
                if target_admin:
                    try:
                        await target_admin.send(
                            f"🚨 **Запрос на досрочный отгул** (< 6 мес.)\n"
                            f"Сотрудник: {message.author.display_name}\n"
                            f"Дата: **{date}**\n\n"
                            f"👮 Вы {target_role} — вам на согласование.",
                            view=view
                        )
                        await message.add_reaction("❗")
                        await message.reply(f"✉️ Запрос отправлен {target_role} {target_admin.display_name}.")
                    except discord.Forbidden:
                        await message.add_reaction("⚠️")
                        await reply_and_delete(message, f"⚠️ Не удалось отправить запрос (ЛС закрыты).")
                    except Exception as e:
                        print(f"[ERROR] {e}")
                        await message.add_reaction("⚠️")
                        await reply_and_delete(message, "⚠️ Ошибка при отправке запроса.")
                return
        except Exception as e:
            print(f"[ERROR] {e}")

    add_dayoff(user_id, date)
    add_history(user_id, f"Отгул на {date}", "Автоодобрен (6+ месяцев)")
    log_to_db(user_id, "add_dayoff", None, f"date={date}, auto_approved=true")
    await message.add_reaction("✅")