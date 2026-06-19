# ============================================================
# commands/slash.py — слеш-команды бота
# ============================================================

import discord
import asyncio
from discord import app_commands

from config import MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY, SUPER_ADMIN_IDS
from db import get_duty_admin, load_all_admins, is_super_admin
from handlers.utils import is_admin_by_id, get_user_by_id, auto_delete
from views.admin import AdminPanelView

# Хранилище активных сообщений
active_admin_panels = {}
active_help_messages = {}


async def register_all(bot):
    
    @bot.tree.command(name="help", description="Правила работы с ботом (общие команды)")
    async def slash_help(interaction: discord.Interaction):
        if interaction.user.id in active_help_messages:
            try:
                await active_help_messages[interaction.user.id].delete()
            except:
                pass
            del active_help_messages[interaction.user.id]

        if isinstance(interaction.channel, discord.DMChannel):
            text = (
                "**📋 Crm_Bot — общие команды**\n\n"
                
                "**🔹 В общем канале (с @Crm_Bot):**\n"
                f"• `пропуск 4` — пропуск на сегодня (макс {MAX_ABSENCE_PER_DAY} ч)\n"
                f"• `пропуск 05.06.2026 2.5` — пропуск на дату\n"
                f"• `отработка 3` — отработка на сегодня (макс {MAX_OVERTIME_PER_DAY} ч)\n"
                f"• `отработка 05.06.2026 6` — отработка на дату\n"
                "• `удалить пропуск 05.06.2026` — удалить пропуск\n"
                "• `удалить отработка 05.06.2026` — удалить отработку\n"
                "• `отгул` / `отгул 20.06.2026` — взять отгул\n"
                "• `отменить отгул 15.06.2026` — отменить свой отгул\n"
                "• `перенести отгул 15.06.2026 на 20.06.2026` — перенести отгул\n\n"
                
                "**🔹 В личных сообщениях:**\n"
                "• `статус` — ваша сводка\n"
                "• `мои отпуска` — отпуска вашего отдела\n"
                "• `мои отгулы` — список ваших отгулов\n"
                "• `кто дежурный` — узнать дежурного админа\n"
                "• `кто суперадмин` — список суперадминов\n"
                "• `отпуск 26.06-26.07` — заявка на отпуск\n"
                "• `изменить отпуск 06.06-10.06 на 03.06-10.06` — заявка на изменение\n\n"
                
                "**📖 Подробнее об отпусках:** `/отпуск`\n"
                "**👑 Администраторам:** `/админ` — панель с кнопками"
            )
        else:
            text = (
                "**📋 Crm_Bot — команды в общем канале**\n\n"
                "Используйте эти команды, упоминая бота: `@Crm_Bot команда`\n\n"
                f"• `пропуск 4` — пропуск на сегодня (макс {MAX_ABSENCE_PER_DAY} ч)\n"
                f"• `пропуск 05.06.2026 2.5` — пропуск на дату\n"
                f"• `отработка 3` — отработка на сегодня (макс {MAX_OVERTIME_PER_DAY} ч)\n"
                f"• `отработка 05.06.2026 6` — отработка на дату\n"
                "• `удалить пропуск 05.06.2026` — удалить пропуск\n"
                "• `удалить отработка 05.06.2026` — удалить отработку\n"
                "• `отгул` / `отгул 20.06.2026` — взять отгул\n"
                "• `отменить отгул 15.06.2026` — отменить свой отгул\n"
                "• `перенести отгул 15.06.2026 на 20.06.2026` — перенести отгул\n\n"
                
                "💡 **Для полного списка команд** напишите `/help` в личных сообщениях с ботом."
            )

        await interaction.response.send_message(text, ephemeral=False)
        message = await interaction.original_response()
        asyncio.create_task(auto_delete(message, 180))
        active_help_messages[interaction.user.id] = message

    @bot.tree.command(name="отпуск", description="Справка по оформлению отпусков")
    async def slash_vacation_help(interaction: discord.Interaction):
        if interaction.user.id in active_help_messages:
            try:
                await active_help_messages[interaction.user.id].delete()
            except:
                pass
            del active_help_messages[interaction.user.id]

        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "🌴 **Управление отпусками доступно только в личных сообщениях**\n\n"
                "Перейдите в ЛС с ботом и введите команду `/отпуск`.",
                ephemeral=True
            )
            return

        help_text = (
            "🌴 **Управление отпусками в Crm_Bot**\n\n"
            "**📅 Форматы дат (год не обязателен):**\n"
            "• `отпуск 26.06-26.07` — на текущий/следующий год\n"
            "• `отпуск 26.06.26-26.07.26` — с коротким годом\n"
            "• `отпуск 26.06.2026-26.07.2026` — с полным годом\n"
            "• Вместо точек можно использовать `/` (пример: 26/06-26/07)\n\n"
            
            "**👤 Команды для пользователей:**\n"
            "• `отпуск ДД.ММ-ДД.ММ` — отправить заявку на отпуск\n"
            "• `мои отпуска` — график отпусков вашего отдела\n"
            "• `изменить отпуск 06.06-10.06 на 03.06-10.06` — заявка на изменение\n"
            "• `изменить отпуск 06.06-10.06 на 0` — заявка на удаление\n\n"
            
            "**👑 Административные команды (в ЛС):**\n"
            "• `отпуск 26.06-26.07 @User` — назначить отпуск сотруднику\n"
            "• `статус отпусков` — все отпуска по отделам\n"
            "• `изменить отпуск 06.06-10.06 на 03.06-10.06 @User` — изменить отпуск сотруднику\n\n"
            
            "**📋 Активные заявки:**\n"
            "• Приходят **только дежурному админу** (или суперадмину)\n"
            "• Админ может одобрить/отклонить через кнопки в ЛС\n"
            "• У пользователя может быть не более 5 активных заявок\n\n"
            
            "**⏰ Ежедневные уведомления:**\n"
            "• Каждое утро в 9:30 МСК бот поздравляет уходящих в отпуск"
        )
        
        await interaction.response.send_message(help_text, ephemeral=False)
        message = await interaction.original_response()
        asyncio.create_task(auto_delete(message, 180))
        active_help_messages[interaction.user.id] = message

    @bot.tree.command(name="админ", description="📋 Панель управления для администраторов")
    async def slash_admin(interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "🔒 **Админ-панель доступна только в личных сообщениях**\n\n"
                "Перейдите в личные сообщения с ботом и введите команду `/админ`.",
                ephemeral=True
            )
            return

        user_id = interaction.user.id
        if not is_admin_by_id(user_id):
            await interaction.response.send_message(
                "⛔ Эта команда только для администраторов.\n\n"
                "Если вы администратор, возможно, вас не назначили. Обратитесь к суперадмину.",
                ephemeral=True
            )
            return

        if user_id in active_admin_panels:
            try:
                await active_admin_panels[user_id].delete()
            except:
                pass
            del active_admin_panels[user_id]

        is_super = user_id in SUPER_ADMIN_IDS or is_super_admin(user_id)

        duty_id = get_duty_admin()
        duty_name = "не назначен"
        if duty_id:
            duty_user = await get_user_by_id(duty_id, interaction.client)
            duty_name = duty_user.display_name if duty_user else f"ID:{duty_id}"

        admins_list = load_all_admins()
        admins_count = len(admins_list)

        embed = discord.Embed(
            title="🛠️ Админ-панель Crm_Bot",
            color=discord.Color.gold() if is_super else discord.Color.blue()
        )

        embed.add_field(
            name="👥 Администраторы",
            value=f"Всего админов: **{admins_count}**\nСуперадмин: <@{SUPER_ADMIN_IDS[0]}>",
            inline=False
        )

        embed.add_field(
            name="👮 Дежурный администратор",
            value=f"Текущий: **{duty_name}**\n\n"
                  f"• Досрочные отгулы (<6 мес.) идут **дежурному**\n"
                  f"• Если дежурный не назначен — **суперадмину**",
            inline=False
        )

        embed.add_field(
            name="📋 Доступные команды (в ЛС боту)",
            value=(
                "**📊 Статистика:** `статус`, `должники`, `история`, `отчёт`, `отчёт_всех`\n"
                "**✏️ Управление:** `уволить`, `обнулить`, `снять`, `new admin`\n"
                "**🏝️ Отпуска:** `отпуск`, `мои отпуска`, `статус отпусков`, `изменить отпуск`\n"
                "**📅 Отгулы:** `@Crm_Bot отгул`, `мои отгулы`, `отгулы @User`\n"
                "**👮 Дежурный:** `кто дежурный`, `стать дежурным`"
            ),
            inline=False
        )

        if is_super:
            embed.add_field(
                name="⚡ Суперадмин",
                value="• `назначить дежурного`, `снять дежурного`\n• Обнуление всех через кнопку ниже",
                inline=False
            )

        embed.set_footer(text="Используйте кнопки ниже")

        view = AdminPanelView(is_super, interaction.client)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        message = await interaction.original_response()
        active_admin_panels[user_id] = message

    @bot.tree.command(name="сотрудник", description="📋 Панель сотрудника (статус, отпуска, отгулы)")
    async def slash_employee(interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "🔒 **Панель сотрудника доступна только в личных сообщениях**\n\n"
                "Перейдите в личные сообщения с ботом и введите команду `/сотрудник`.",
                ephemeral=True
            )
            return

        if interaction.user.id in active_help_messages:
            try:
                await active_help_messages[interaction.user.id].delete()
            except:
                pass
            del active_help_messages[interaction.user.id]

        # Получаем никнейм пользователя на сервере
        server_nick = interaction.user.display_name
        for guild in interaction.client.guilds:
            member = guild.get_member(interaction.user.id)
            if member:
                server_nick = member.display_name
                break

        embed = discord.Embed(
            title="📋 Панель сотрудника",
            description=f"Добро пожаловать, {server_nick}!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="📊 Доступные действия",
            value=(
                "• **Статус** — ваша сводка (баланс, пропуски, отработки)\n"
                "• **Мои отпуска** — график отпусков вашего отдела\n"
                "• **Создать отпуск** — инструкция по заявке\n"
                "• **Мои отгулы** — список ваших отгулов"
            ),
            inline=False
        )
        embed.set_footer(text="Панель закроется через 5 минут бездействия")

        from views.user_panel import UserPanelView
        view = UserPanelView(interaction.user.id, server_nick, interaction.client)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        message = await interaction.original_response()
        active_help_messages[interaction.user.id] = message

    try:
        synced = await bot.tree.sync()
        print(f"✅ Синхронизировано {len(synced)} слеш-команд.")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")
