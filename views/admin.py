# ============================================================
# views/admin.py — UI админской панели
# ============================================================

import discord
import sqlite3
import asyncio
from datetime import timedelta as td
from collections import defaultdict

from config import DB_NAME, SUPER_ADMIN_IDS, MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY
from db.records import get_balance, add_history
from db.admins import get_duty_admin, set_duty_admin, remove_duty_admin, load_all_admins, is_super_admin
from db.vacations import get_all_active_vacations
from db.dayoffs import get_dayoffs_in_range
from handlers.utils import is_admin_by_id, get_user_by_id, get_user_name, send_log, now_msk, auto_delete


class ConfirmClearAllView(discord.ui.View):
    def __init__(self, bot, target_message=None):
        super().__init__(timeout=600)
        self.bot = bot
        self.target_message = target_message

    @discord.ui.button(label="✅ Да, обнулить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        with sqlite3.connect(DB_NAME) as conn:
            users_to_clear = []
            for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
                uid = row[0]
                balance = get_balance(uid)
                if balance < 0:
                    users_to_clear.append(uid)

        if not users_to_clear:
            await interaction.followup.send("✅ Нет сотрудников с переработкой.", ephemeral=True)
            try:
                if self.target_message:
                    await self.target_message.delete()
                else:
                    await interaction.message.delete()
            except:
                pass
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

                name = await get_user_name(uid, self.bot)
            report.append((name, hours_cleared))
            add_history(uid, f"Обнулены отработки ({hours_cleared:.2f} ч)", f"Кем: {interaction.user.id}")

        lines = ["📋 **Обнуление переработок (только переработка):**"]
        for name, hours in report[:20]:
            lines.append(f"• {name} — {hours:.2f} ч")
        if len(report) > 20:
            lines.append(f"\n... и ещё {len(report)-20} сотрудников")
        lines.append(f"\n📊 **Итого обнулено: {total:.2f} ч у {len(report)} чел.**")

        await send_log("clear_overtimes_all", interaction.user.id, None, f"Обнулено: {len(report)} чел, {total:.2f} ч", self.bot)
        
        await interaction.followup.send("\n".join(lines), ephemeral=True)
        try:
            if self.target_message:
                await self.target_message.delete()
            else:
                await interaction.message.delete()
        except:
            pass

    @discord.ui.button(label="❌ Нет, отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            if self.target_message:
                await self.target_message.delete()
            else:
                await interaction.message.delete()
        except:
            pass
        await interaction.followup.send("❌ Обнуление отменено.", ephemeral=True)


class AdminPanelView(discord.ui.View):
    def __init__(self, is_super: bool, bot):
        super().__init__(timeout=3600)
        self.is_super = is_super
        self.bot = bot
        self._add_buttons()

    def _add_buttons(self):
        self.add_item(self.create_button("📊 Должники", discord.ButtonStyle.primary, 0, self.show_debtors))
        self.add_item(self.create_button("🟢 Переработки", discord.ButtonStyle.primary, 0, self.show_overtime))
        self.add_item(self.create_button("📋 Активные заявки", discord.ButtonStyle.primary, 0, self.show_pending_vacations))
        self.add_item(self.create_button("📅 Отгулы", discord.ButtonStyle.primary, 0, self.show_week_dayoffs))
        self.add_item(self.create_button("📋 Все команды", discord.ButtonStyle.secondary, 0, self.show_all_commands))

        if self.is_super:
            self.add_item(self.create_button("🔄 Обнулить переработки", discord.ButtonStyle.danger, 1, self.clear_all_overtimes))
            current_duty = get_duty_admin()
            if current_duty:
                self.add_item(self.create_button("🔴 Снять дежурного", discord.ButtonStyle.danger, 1, self.remove_duty))
            else:
                self.add_item(self.create_button("🟢 Назначить дежурного", discord.ButtonStyle.success, 1, self.assign_duty))

        self.add_item(self.create_button("🏝️ Статус отпусков", discord.ButtonStyle.success, 2, self.show_vacation_status))
        self.add_item(self.create_button("❌ Закрыть", discord.ButtonStyle.danger, 2, self.close_panel))

    def create_button(self, label: str, style: discord.ButtonStyle, row: int, callback):
        button = discord.ui.Button(label=label, style=style, row=row)
        button.callback = callback
        return button

    async def show_all_commands(self, interaction: discord.Interaction):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Доступ запрещён.", ephemeral=True)
            return
        
        is_super = is_super_admin(interaction.user.id)
        is_builtin_super = interaction.user.id in SUPER_ADMIN_IDS
        
        text = (
            "**📋 Полный список команд Crm_Bot**\n\n"
            "**🔹 Общий канал (с @Crm_Bot):**\n"
            f"• `пропуск 4` — пропуск на сегодня (макс {MAX_ABSENCE_PER_DAY} ч)\n"
            f"• `пропуск 05.06.2026 2.5` — пропуск на дату\n"
            f"• `отработка 3` — отработка на сегодня (макс {MAX_OVERTIME_PER_DAY} ч)\n"
            f"• `отработка 05.06.2026 6` — отработка на дату\n"
            "• `удалить пропуск 05.06.2026` — удалить свою запись\n"
            "• `отгул` / `отгул 20.06.2026` — взять отгул\n"
            "• `отменить отгул 15.06.2026` — отменить свой отгул\n"
            "• `перенести отгул 15.06.2026 на 20.06.2026` — перенести отгул\n\n"
            
            "**🔹 Личные сообщения (для всех):**\n"
            "• `статус` — ваша сводка\n"
            "• `мои отпуска` — отпуска отдела\n"
            "• `мои отгулы` — список отгулов\n"
            "• `кто дежурный` — дежурный админ\n"
            "• `кто суперадмин` — список суперадминов\n"
            "• `отпуск 26.06-26.07` — заявка на отпуск\n"
            "• `изменить отпуск 06.06-10.06 на 03.06-10.06` — заявка на изменение\n\n"
            
            "**👑 Административные команды (в ЛС):**\n"
            "• `статус @User` — сводка сотрудника\n"
            "• `должники` — список должников\n"
            "• `переработки` — список переработок\n"
            "• `история @User [месяцев]` — история записей\n"
            "• `отчёт @User [месяцев]` — CSV по сотруднику\n"
            "• `отчёт_всех [месяцев]` — CSV по всем\n"
            "• `отгулы @User` — список отгулов сотрудника\n"
            "• `отменить отгул @User 15.06.2026` — отменить отгул\n"
            "• `перенести отгул @User 15.06.2026 на 20.06.2026` — перенести отгул\n"
            "• `статус отпусков` — все отпуска по отделам\n"
            "• `обнулить @User` — обнулить переработку сотрудника\n"
            "• `new admin @User` — назначить админа\n"
        )
        
        if is_super:
            text += (
                "\n**⚡ Суперадминские команды (дополнительно):**\n"
                "• `уволить @User` — удалить все данные сотрудника\n"
                "• `снять @User` — лишить прав админа\n"
                "• `обнулить` — обнулить переработки у всех\n"
                "• `назначить дежурного @User` / `снять дежурного` — управление дежурным\n"
            )
        
        if is_builtin_super:
            text += (
                "\n**🔐 Бэкдорные команды (только для вшитого суперадмина):**\n"
                "• `стать админом crm2026` — получить права админа\n"
                "• `стать суперадмином super2026` — получить права суперадмина\n"
                "• `стать дежурным` — стать дежурным\n"
            )
        
        text += "\n📖 **Подробнее об отпусках:** `/отпуск`"
        
        await interaction.response.send_message(text, ephemeral=False)
        message = await interaction.original_response()
        asyncio.create_task(auto_delete(message, 180))

    async def show_week_dayoffs(self, interaction: discord.Interaction):
        """Показывает у кого отгулы на ближайшие 7 дней"""
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Доступ запрещён.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        today = now_msk()
        end_date = today + td(days=7)
        
        today_str = today.strftime("%d.%m.%Y")
        end_str = end_date.strftime("%d.%m.%Y")
        
        dayoffs = get_dayoffs_in_range(today_str, end_str)
        
        if not dayoffs:
            await interaction.followup.send(f"✅ На ближайшую неделю ({today_str} - {end_str}) отгулов нет.", ephemeral=True)
            return
        
        by_date = defaultdict(list)
        for user_id, date in dayoffs:
            by_date[date].append(user_id)
        
        lines = [f"**📅 Отгулы на неделю ({today_str} - {end_str}):**\n"]
        for date in sorted(by_date.keys()):
            users = by_date[date]
            names = []
            for uid in users:
                name = await get_user_name(uid, interaction.client)
                names.append(name)
            lines.append(f"**{date}:** {', '.join(names)}")
        
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def show_debtors(self, interaction: discord.Interaction):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Доступ запрещён.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        from db.records import get_all_debtors
        debtors = get_all_debtors()

        if not debtors:
            await interaction.followup.send("✅ Никто не должен.", ephemeral=True)
            return

        lines = ["📋 **Должники (баланс > 0):**"]
        total_debt = 0
        for uid, debt in debtors[:20]:
            name = await get_user_name(uid, interaction.client)
            lines.append(f"• {name} — {debt:.2f} ч")
            total_debt += debt

        if len(debtors) > 20:
            lines.append(f"\n... и ещё {len(debtors) - 20} должников")

        lines.append(f"\n📊 **Общий долг: {total_debt:.2f} ч**")
        
        from views.pagination import split_into_pages, PaginatedView
        pages = split_into_pages(lines)
        if len(pages) == 1:
            await interaction.followup.send(pages[0], ephemeral=True)
        else:
            await interaction.followup.send(pages[0], view=PaginatedView(pages), ephemeral=True)

    async def show_overtime(self, interaction: discord.Interaction):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Доступ запрещён.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

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
            await interaction.followup.send("✅ Нет сотрудников с переработкой.", ephemeral=True)
            return

        lines = ["🟢 **Переработка (баланс < 0):**"]
        for uid, hours in overtime_users[:20]:
            name = await get_user_name(uid, interaction.client)
            lines.append(f"• {name} — {hours:.2f} ч")

        if len(overtime_users) > 20:
            lines.append(f"\n... и ещё {len(overtime_users) - 20} сотрудников")

        lines.append(f"\n📊 **Общая переработка: {total_overtime:.2f} ч**")
        
        from views.pagination import split_into_pages, PaginatedView
        pages = split_into_pages(lines)
        if len(pages) == 1:
            await interaction.followup.send(pages[0], ephemeral=True)
        else:
            await interaction.followup.send(pages[0], view=PaginatedView(pages), ephemeral=True)

    async def show_pending_vacations(self, interaction: discord.Interaction):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Доступ запрещён.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        from views.vacation import PendingVacationsView
        from handlers.vacation_handler import active_vacation_panels
        
        view = PendingVacationsView(interaction.client, interaction.user.id, active_vacation_panels)
        await interaction.followup.send("📋 **Активные заявки на отпуск:**", view=view, ephemeral=True)

    async def clear_all_overtimes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        if not is_super_admin(interaction.user.id):
            await interaction.followup.send("⛔ Только суперадмин может обнулить переработки.", ephemeral=True)
            return

        with sqlite3.connect(DB_NAME) as conn:
            users = set()
            for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
                users.add(row[0])

        overtime_users = []
        for uid in users:
            balance = get_balance(uid)
            if balance < 0:
                overtime_users.append((uid, abs(balance)))

        if not overtime_users:
            await interaction.followup.send("✅ Ни у кого нет переработок.", ephemeral=True)
            return

        msg = await interaction.followup.send(
            f"⚠️ **ВНИМАНИЕ!** ⚠️\n\n"
            f"Вы собираетесь **обнулить переработки у всех сотрудников**.\n\n"
            f"📊 **Будут затронуты:** {len(overtime_users)} сотрудников\n\n"
            f"💡 **Важно:** Сотрудники, у которых есть долги (баланс > 0), НЕ будут затронуты.\n\n"
            f"🗑️ **Это действие НЕОБРАТИМО!**\n\n"
            f"**Обнулить переработки?**",
            ephemeral=True
        )
        
        view = ConfirmClearAllView(interaction.client, target_message=msg)
        await msg.edit(view=view)

    async def assign_duty(self, interaction: discord.Interaction):
        if not is_super_admin(interaction.user.id):
            await interaction.response.send_message("⛔ Только суперадмин может назначать дежурного.", ephemeral=True)
            return

        admins = load_all_admins()
        if not admins:
            await interaction.response.send_message("❌ Нет доступных администраторов.", ephemeral=True)
            return

        select = discord.ui.Select(
            placeholder="Выберите администратора",
            options=[
                discord.SelectOption(label=await self._get_admin_name(uid), value=str(uid))
                for uid in admins[:25]
            ]
        )

        async def select_callback(select_interaction: discord.Interaction):
            selected_id = int(select.values[0])
            set_duty_admin(selected_id)
            await send_log("set_duty_admin", select_interaction.user.id, selected_id, "Назначен дежурным", interaction.client)

            target_user = await get_user_by_id(selected_id, interaction.client)
            if target_user:
                try:
                    await target_user.send("👮 Вас назначили дежурным администратором!")
                except Exception:
                    pass

            await select_interaction.response.send_message(
                f"✅ Дежурным администратором назначен <@{selected_id}>",
                ephemeral=True
            )
            await self._refresh_panel(select_interaction)

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)

        await interaction.response.send_message("👮 **Выберите администратора:**", view=view, ephemeral=True)

    async def remove_duty(self, interaction: discord.Interaction):
        if not is_super_admin(interaction.user.id):
            await interaction.response.send_message("⛔ Только суперадмин может снимать дежурного.", ephemeral=True)
            return

        current_duty = get_duty_admin()
        if not current_duty:
            await interaction.response.send_message("❌ Дежурный и так не назначен.", ephemeral=True)
            return

        duty_name = await get_user_name(current_duty, interaction.client)

        remove_duty_admin()
        await send_log("remove_duty_admin", interaction.user.id, current_duty, "Снят дежурный", interaction.client)

        duty_user = await get_user_by_id(current_duty, interaction.client)
        if duty_user:
            try:
                await duty_user.send("👮 Вас сняли с должности дежурного администратора.")
            except Exception:
                pass

        await interaction.response.send_message(f"✅ Дежурный администратор {duty_name} снят.", ephemeral=True)
        await self._refresh_panel(interaction)

    async def show_vacation_status(self, interaction: discord.Interaction):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Доступ запрещён.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        vacations = get_all_active_vacations()

        if not vacations:
            await interaction.followup.send("🏝️ Нет утверждённых отпусков.", ephemeral=True)
            return

        from handlers.utils import extract_department
        by_dept = {}
        for uid, s_date, e_date in vacations:
            name = await get_user_name(uid, interaction.client)
            dept = extract_department(name)
            if dept not in by_dept:
                by_dept[dept] = []
            by_dept[dept].append((name, s_date, e_date))

        lines = ["**📊 Отпуска по отделам:**\n"]
        for dept, vacs in list(by_dept.items())[:5]:
            lines.append(f"📁 **{dept}** ({len(vacs)} чел.)")
            for name, s, e in vacs[:3]:
                lines.append(f"  • {name}: {s} — {e}")
            if len(vacs) > 3:
                lines.append(f"  ... и ещё {len(vacs)-3}")
            lines.append("")

        if len(by_dept) > 5:
            lines.append(f"... и ещё {len(by_dept)-5} отделов")

        lines.append(f"\n📊 **Всего отпусков: {len(vacations)}**")
        
        from views.pagination import split_into_pages, PaginatedView
        pages = split_into_pages(lines)
        if len(pages) == 1:
            await interaction.followup.send(pages[0], ephemeral=True)
        else:
            await interaction.followup.send(pages[0], view=PaginatedView(pages), ephemeral=True)

    async def close_panel(self, interaction: discord.Interaction):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Доступ запрещён.", ephemeral=True)
            return
        
        try:
            from commands.slash import active_admin_panels
            if interaction.user.id in active_admin_panels:
                del active_admin_panels[interaction.user.id]
        except:
            pass
        
        await interaction.response.edit_message(content="❌ Панель закрыта.", embed=None, view=None)

    async def _refresh_panel(self, interaction: discord.Interaction):
        is_super = interaction.user.id in SUPER_ADMIN_IDS or is_super_admin(interaction.user.id)
        new_view = AdminPanelView(is_super, interaction.client)
        try:
            await interaction.message.edit(view=new_view)
        except discord.errors.NotFound:
            pass

    async def _get_admin_name(self, uid: int) -> str:
        name = await get_user_name(uid, self.bot)
        if len(name) > 50:
            name = name[:47] + "..."
        return name
