# ============================================================
# bot.py — инициализация + запуск + слеш-команды
# ============================================================

import asyncio
import sqlite3
from datetime import datetime

import discord
from discord.ext import commands, tasks
from discord import app_commands

from config import (
    TOKEN, GENERAL_CHANNEL_ID, LOG_CHANNEL_ID,
    SUPER_ADMIN_IDS, MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY,
    DB_NAME, TIMEZONE_OFFSET
)
from db import (
    init_db, load_all_admins, get_vacation_by_id,
    update_vacation_status, apply_vacation_change,
    get_vacations_starting_today
)
from handlers.dm_handler import handle_dm
from handlers.channel_handler import handle_channel
from handlers.utils import (
    now_msk, today_msk, extract_department, get_user_by_id, is_admin
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
current_admins = []


class VacationApprovalView(discord.ui.View):
    def __init__(self, vac_id: int):
        super().__init__(timeout=None)
        self.vac_id = vac_id

    @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.green, custom_id="approve_vac")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user.id, current_admins):
            await interaction.response.send_message("⛔ Вы не администратор.", ephemeral=True)
            return
        vac = get_vacation_by_id(self.vac_id)
        if not vac:
            await interaction.response.send_message("❌ Заявка не найдена в базе.", ephemeral=True)
            return

        target_user = await get_user_by_id(vac["user_id"], bot)
        target_name = target_user.display_name if target_user else f"ID:{vac['user_id']}"

        if vac["status"] == "pending_approval":
            update_vacation_status(self.vac_id, "approved")
            msg = f"✅ Отпуск для {target_name} ({vac['start_date']} - {vac['end_date']}) успешно утвержден!"
            if target_user:
                try:
                    await target_user.send(
                        f"🎉 Ваша заявка на отпуск с {vac['start_date']} по {vac['end_date']} была **одобрена** администратором!"
                    )
                except discord.Forbidden:
                    pass
                except Exception as e:
                    print(f"[WARN] Не удалось отправить ЛС об одобрении отпуска: {e}")
        elif vac["status"] == "pending_change":
            apply_vacation_change(self.vac_id)
            msg = f"✅ Изменение отпуска для {target_name} на даты ({vac['new_start_date']} - {vac['new_end_date']}) успешно утверждено!"
            if target_user:
                try:
                    await target_user.send(
                        f"🎉 Изменение вашего отпуска на период с {vac['new_start_date']} по {vac['new_end_date']} было **одобрено**!"
                    )
                except discord.Forbidden:
                    pass
                except Exception as e:
                    print(f"[WARN] Не удалось отправить ЛС об изменении отпуска: {e}")
        else:
            await interaction.response.send_message("⚠️ Данная заявка уже была обработана ранее.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content=f"~~{interaction.message.content}~~\n\n{msg}", view=self)
        await interaction.response.defer()

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.red, custom_id="reject_vac")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user.id, current_admins):
            await interaction.response.send_message("⛔ Вы не администратор.", ephemeral=True)
            return
        vac = get_vacation_by_id(self.vac_id)
        if not vac:
            await interaction.response.send_message("❌ Заявка не найдена.", ephemeral=True)
            return

        target_user = await get_user_by_id(vac["user_id"], bot)
        target_name = target_user.display_name if target_user else f"ID:{vac['user_id']}"

        if vac["status"] == "pending_approval":
            update_vacation_status(self.vac_id, "rejected")
            msg = f"❌ Заявка на отпуск для {target_name} была отклонена."
        elif vac["status"] == "pending_change":
            update_vacation_status(self.vac_id, "approved")
            msg = f"❌ Запрос на изменение отпуска для {target_name} отклонен. Оставлены старые даты."
        else:
            await interaction.response.send_message("⚠️ Данная заявка уже была обработана.", ephemeral=True)
            return
        if target_user:
            try:
                await target_user.send("⚠️ Ваша заявка/запрос на изменение отпуска были **отклонены** администратором.")
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[WARN] Не удалось отправить ЛС об отклонении: {e}")
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(content=f"~~{interaction.message.content}~~\n\n{msg}", view=self)
        await interaction.response.defer()


@tasks.loop(minutes=1)
async def celebrate_vacations_task():
    now = now_msk()
    if now.hour == 9 and now.minute == 30:
        today_str = now.strftime("%d.%m.%Y")
        todays_vacations = get_vacations_starting_today(today_str)
        if not todays_vacations:
            return
        general_channel = bot.get_channel(GENERAL_CHANNEL_ID)
        if not general_channel:
            return
        for user_id, s_date, e_date in todays_vacations:
            member = await get_user_by_id(user_id, bot)
            mention_str = member.mention if member else f"ID:{user_id}"
            try:
                d1 = datetime.strptime(s_date, "%d.%m.%Y")
                d2 = datetime.strptime(e_date, "%d.%m.%Y")
                days_text = f"на **{(d2 - d1).days + 1} дн.**"
            except:
                days_text = ""
            try:
                await general_channel.send(
                    f"🌴✈️ **Ура, отпуск!** ✈️🌴\n\n"
                    f"Сегодня {mention_str} официально отправляется отдыхать {days_text} "
                    f"(с `{s_date}` по `{e_date}`)!\n"
                    f"Желаем круто провести время, набраться сил, отключить рабочие чаты и хорошенько перезагрузиться! 🎉☀️"
                )
            except Exception as e:
                print(f"[ERROR] Не удалось отправить поздравление в общий чат: {e}")


@bot.event
async def on_ready():
    global current_admins
    init_db()
    current_admins = load_all_admins()

    if not celebrate_vacations_task.is_running():
        celebrate_vacations_task.start()

    try:
        synced = await bot.tree.sync()
        print(f"✅ Бот {bot.user} запущен. Синхронизировано {len(synced)} слеш-команд.")
        print(f"👑 Админы: {current_admins}")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")


@bot.tree.command(name="help", description="Правила работы с ботом")
async def slash_help(interaction: discord.Interaction):
    user_id = interaction.user.id
    is_user_admin = is_admin(user_id, current_admins)
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
        "• > 0 → нужно отработать\n• = 0 → долгов нет\n• < 0 → переработка\n\n"
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
            "• `отпуск` — справка по отпускам\n"
            "• `статус отпусков` — сводка по отделам\n"
            "• `@Crm_Bot удалить пропуск ДД.ММ.ГГГГ @User` — удалить чужую запись"
        )
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="отпуск", description="Справка по оформлению отпусков")
async def slash_vacation_help(interaction: discord.Interaction):
    is_dm = isinstance(interaction.channel, discord.DMChannel)
    help_text = (
        "🌴 **Управление отпусками в Crm_Bot**\n\n"
        "⚠️ **Важно:** Подача всех заявок и работа с отпусками происходит **СТРОГО в личных сообщениях боту**!\n\n"
        "**Пользовательские команды (в ЛС боту):**\n"
        "• `отпуск ДД.ММ.ГГ-ДД.ММ.ГГ` — Отправить заявку на отпуск админу.\n"
        "• `мои отпуска` — Показать таблицу отпусков вашего отдела.\n"
        "• `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на ДД.ММ.ГГ-ДД.ММ.ГГ` — Отправить заявку на перенос существующего отпуска.\n"
        "• `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на 0` — Полное удаление существующего отпуска.\n\n"
        "**Административные команды (в ЛС боту):**\n"
        "• `отпуск ДД.ММ.ГГ-ДД.ММ.ГГ @Юзер` — Назначить отпуск сотруднику напрямую (без подтверждения).\n"
        "• `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на ДД.ММ.ГГ-ДД.ММ.ГГ @Юзер` — Изменить даты отпуска сотруднику напрямую.\n"
        "• `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на 0 @Юзер` — Удалить отпуск сотрудника напрямую.\n"
        "• `статус отпусков` — Показать таблицу всех отпусков, разбитую по отделам."
    )
    if not is_dm:
        await interaction.response.send_message("✉️ Инструкция отправлена в личные сообщения.", ephemeral=True)
        try:
            await interaction.user.send(help_text)
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"[WARN] Не удалось отправить справку в ЛС: {e}")
    else:
        await interaction.response.send_message(help_text)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    if isinstance(message.channel, discord.DMChannel):
        await handle_dm(message, bot, current_admins, VacationApprovalView)
        return
    if message.channel.id != GENERAL_CHANNEL_ID:
        return
    if bot.user not in message.mentions:
        return
    await handle_channel(message, bot, current_admins)


if __name__ == "__main__":
    print("🚀 Запускаю Crm_Bot...")
    bot.run(TOKEN)