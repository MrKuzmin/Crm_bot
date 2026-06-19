# ============================================================
# views/vacation.py — UI для управления отпусками
# ============================================================

import discord
import sqlite3

from config import DB_NAME
from db.records import add_history
from db.vacations import (
    get_vacation_by_id, update_vacation_status, apply_vacation_change,
    get_all_active_vacations
)
from handlers.utils import is_admin_by_id, get_user_by_id, send_log
from handlers.vacation_handler import active_vacation_panels
from db.user_names import get_cached_name


class VacationApprovalView(discord.ui.View):
    def __init__(self, vac_id: int, status: str = "pending_approval"):
        super().__init__(timeout=604800)
        self.vac_id = vac_id
        self.status = status

    @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin_by_id(interaction.user.id):
            await interaction.response.send_message("⛔ Вы не администратор.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        vac = get_vacation_by_id(self.vac_id)
        if not vac:
            await interaction.followup.send("❌ Заявка не найдена.", ephemeral=True)
            try:
                await interaction.message.delete()
            except:
                pass
            return

        target_user = await get_user_by_id(vac["user_id"], interaction.client)
        target_name = target_user.display_name if target_user else f"ID:{vac['user_id']}"

        if vac["status"] == "pending_approval":
            update_vacation_status(self.vac_id, "approved")
            msg = f"✅ Отпуск для {target_name} ({vac['start_date']} - {vac['end_date']}) утвержден!"
            if target_user:
                try:
                    await target_user.send(f"🎉 Ваш отпуск с {vac['start_date']} по {vac['end_date']} **одобрен**!")
                except:
                    pass
        elif vac["status"] == "pending_change":
            apply_vacation_change(self.vac_id)
            msg = f"✅ Изменение отпуска для {target_name} на ({vac['new_start_date']} - {vac['new_end_date']}) утверждено!"
            if target_user:
                try:
                    await target_user.send(f"🎉 Изменение отпуска на {vac['new_start_date']} - {vac['new_end_date']} **одобрено**!")
                except:
                    pass
        else:
            await interaction.followup.send("⚠️ Заявка уже обработана.", ephemeral=True)
            try:
                await interaction.message.delete()
            except:
                pass
            return

        if interaction.user.id in active_vacation_panels:
            try:
                old_message = active_vacation_panels[interaction.user.id]
                new_view = PendingVacationsView(interaction.client, interaction.user.id, active_vacation_panels)
                await old_message.edit(content="📋 **Активные заявки на отпуск:**", view=new_view)
            except:
                pass

        await interaction.followup.send(msg, ephemeral=True)
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
        
        vac = get_vacation_by_id(self.vac_id)
        if not vac:
            await interaction.followup.send("❌ Заявка не найдена.", ephemeral=True)
            try:
                await interaction.message.delete()
            except:
                pass
            return

        target_user = await get_user_by_id(vac["user_id"], interaction.client)
        target_name = target_user.display_name if target_user else f"ID:{vac['user_id']}"

        update_vacation_status(self.vac_id, "rejected")
        
        if target_user:
            try:
                await target_user.send(f"❌ Ваша заявка на отпуск с {vac['start_date']} по {vac['end_date']} **отклонена**.")
            except:
                pass

        if interaction.user.id in active_vacation_panels:
            try:
                old_message = active_vacation_panels[interaction.user.id]
                new_view = PendingVacationsView(interaction.client, interaction.user.id, active_vacation_panels)
                await old_message.edit(content="📋 **Активные заявки на отпуск:**", view=new_view)
            except:
                pass

        await interaction.followup.send(f"❌ Заявка на отпуск для {target_name} отклонена.", ephemeral=True)
        try:
            await interaction.message.delete()
        except:
            pass


class PendingVacationsView(discord.ui.View):
    def __init__(self, bot, admin_id: int, panels_dict: dict):
        super().__init__(timeout=3600)
        self.bot = bot
        self.admin_id = admin_id
        self.panels_dict = panels_dict
        self.refresh()

    def refresh(self):
        self.clear_items()
        
        with sqlite3.connect(DB_NAME) as conn:
            rows = conn.execute(
                "SELECT id, user_id, start_date, end_date, status, new_start_date, new_end_date FROM vacations "
                "WHERE status IN ('pending_approval', 'pending_change')"
            ).fetchall()
        
        if not rows:
            self.add_item(discord.ui.Button(label="✅ Нет активных заявок", disabled=True, style=discord.ButtonStyle.secondary))
            return
        
        from collections import defaultdict
        user_vacations = defaultdict(list)
        
        for vac_id, user_id, start_date, end_date, status, new_start, new_end in rows:
            if user_id == self.admin_id:
                continue
            user_vacations[user_id].append({
                'id': vac_id,
                'start_date': start_date,
                'end_date': end_date,
                'status': status,
                'new_start_date': new_start,
                'new_end_date': new_end
            })
        
        for user_id, vacations in user_vacations.items():
            name = get_cached_name(user_id) or f"ID:{user_id}"
            display_name = name if len(name) <= 25 else name[:22] + "..."
            
            vacation_count = len(vacations)
            
            if vacation_count == 1:
                vac = vacations[0]
                if vac['status'] == 'pending_change':
                    desc = f"изменить {vac['start_date']}→{vac['new_start_date']}"
                else:
                    desc = f"{vac['start_date']}-{vac['end_date']}"
            else:
                desc = f"{vacation_count} заявки"
            
            label = f"📋 {display_name}: {desc}"
            if len(label) > 80:
                label = label[:77] + "..."
            
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"user_{user_id}"
            )
            
            async def button_callback(interaction: discord.Interaction, uid=user_id, uname=name, uvacations=vacations):
                embed = discord.Embed(
                    title=f"📋 Заявки на отпуск: {uname}",
                    color=discord.Color.blue()
                )
                
                for vac in uvacations:
                    if vac['status'] == 'pending_approval':
                        embed.add_field(
                            name=f"🆕 Заявка #{vac['id']}",
                            value=f"Даты: {vac['start_date']} - {vac['end_date']}\nСтатус: ⏳ ожидает",
                            inline=False
                        )
                    elif vac['status'] == 'pending_change':
                        embed.add_field(
                            name=f"🔄 Изменение #{vac['id']}",
                            value=f"Было: {vac['start_date']} - {vac['end_date']}\nСтатус: ⏳ ожидает\nСтало: {vac['new_start_date']} - {vac['new_end_date']}",
                            inline=False
                        )
                
                embed.set_footer(text="Используйте кнопки ниже для каждой заявки")
                
                view = UserVacationsView(uid, uname, uvacations, self.bot, self.admin_id, self.panels_dict)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
            button.callback = button_callback
            self.add_item(button)
        
        refresh_button = discord.ui.Button(label="🔄 Обновить", style=discord.ButtonStyle.secondary, custom_id="refresh")
        
        async def refresh_callback(interaction: discord.Interaction):
            if interaction.user.id == self.admin_id:
                self.refresh()
                await interaction.response.edit_message(view=self)
            else:
                await interaction.response.send_message("⛔ Только администратор может обновить панель.", ephemeral=True)
        
        refresh_button.callback = refresh_callback
        self.add_item(refresh_button)


class UserVacationsView(discord.ui.View):
    def __init__(self, user_id: int, user_name: str, vacations: list, bot, admin_id: int, panels_dict: dict):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.user_name = user_name
        self.vacations = vacations
        self.bot = bot
        self.admin_id = admin_id
        self.panels_dict = panels_dict
        self._add_buttons()

    def _add_buttons(self):
        for vac in self.vacations:
            if vac['status'] == 'pending_approval':
                label = f"📝 {vac['start_date']}-{vac['end_date']}"
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"vac_{vac['id']}")
                
                async def callback(interaction: discord.Interaction, vac_id=vac['id'], start=vac['start_date'], end=vac['end_date']):
                    view = VacationApprovalView(vac_id, "pending_approval")
                    await interaction.response.send_message(
                        f"**Заявка на новый отпуск от {self.user_name}**\n"
                        f"Период: {start} - {end}\n\n"
                        f"Что делаем?",
                        view=view,
                        ephemeral=True
                    )
                button.callback = callback
                self.add_item(button)
                
            elif vac['status'] == 'pending_change':
                label = f"🔄 {vac['start_date']}→{vac['new_start_date']}"
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"vac_{vac['id']}")
                
                async def callback(interaction: discord.Interaction, vac_id=vac['id'], old_start=vac['start_date'], old_end=vac['end_date'], new_start=vac['new_start_date'], new_end=vac['new_end_date']):
                    view = VacationApprovalView(vac_id, "pending_change")
                    await interaction.response.send_message(
                        f"**Запрос на изменение отпуска от {self.user_name}**\n"
                        f"Было: {old_start} - {old_end}\n"
                        f"Стало: {new_start} - {new_end}\n\n"
                        f"Что делаем?",
                        view=view,
                        ephemeral=True
                    )
                button.callback = callback
                self.add_item(button)
        
        # кнопки "Назад" и "Закрыть" удалены по просьбе пользователя
