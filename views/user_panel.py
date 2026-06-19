# ============================================================
# views/user_panel.py — пользовательская панель /сотрудник
# ============================================================

import discord

from handlers.utils import format_status, get_user_by_id, today_msk, now_msk
from db.dayoffs import get_user_dayoffs
from db.vacations import get_all_active_vacations
from handlers.utils import extract_department


class UserPanelView(discord.ui.View):
    def __init__(self, user_id: int, user_name: str, bot):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.user_name = user_name
        self.bot = bot

    @discord.ui.button(label="📊 Статус", style=discord.ButtonStyle.primary, row=0)
    async def show_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ Это ваша панель.", ephemeral=True)
            return
        status_text = format_status(self.user_id, self.user_name)
        await interaction.response.send_message(status_text, ephemeral=True)

    @discord.ui.button(label="🏝️ Мои отпуска", style=discord.ButtonStyle.primary, row=0)
    async def my_vacations(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ Это ваша панель.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        vacations = get_all_active_vacations()
        if not vacations:
            await interaction.followup.send("🏝️ Нет утверждённых отпусков.", ephemeral=True)
            return
        current_year = now_msk().year
        by_dept = {}
        today = today_msk()
        for uid, s_date, e_date in vacations:
            # Показываем только отпуска за текущий год и будущие
            try:
                end_year = int(e_date.split('.')[-1])
                if end_year < current_year:
                    continue
            except (ValueError, IndexError):
                pass
            user = await get_user_by_id(uid, self.bot)
            name = user.display_name if user else f"ID:{uid}"
            dept = extract_department(name)
            if dept not in by_dept:
                by_dept[dept] = []
            by_dept[dept].append((name, s_date, e_date))
        lines = ["**🏝️ Отпуска по отделам:**\n"]
        for dept, vacs in list(by_dept.items())[:5]:
            lines.append(f"📁 **{dept}** ({len(vacs)} чел.)")
            for name, s, e in vacs[:3]:
                # Отгулянные — зачёркиваем и ставим ✅
                if e < today:
                    entry = f"  ~~• {name}: {s} — {e}~~ ✅"
                else:
                    entry = f"  • {name}: {s} — {e}"
                lines.append(entry)
            if len(vacs) > 3:
                lines.append(f"  ... и ещё {len(vacs)-3}")
            lines.append("")
        if len(by_dept) > 5:
            lines.append(f"... и ещё {len(by_dept)-5} отделов")
        lines.append(f"\n📊 **Всего отпусков: {len(vacations)}**")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @discord.ui.button(label="🌴 Создать отпуск", style=discord.ButtonStyle.success, row=1)
    async def create_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ Это ваша панель.", ephemeral=True)
            return
        text = (
            "🌴 **Создание заявки на отпуск**\n\n"
            "Напишите в ЛС:\n"
            "`отпуск ДД.ММ-ДД.ММ` — например: `отпуск 26.06-26.07`\n\n"
            "**Примеры:**\n"
            "• `отпуск 26.06-26.07`\n"
            "• `отпуск 26.06.2026-26.07.2026`\n"
            "• `отпуск 26/06-26/07`\n"
            "• `изменить отпуск 06.06-10.06 на 03.06-10.06`\n\n"
            "📖 Подробнее: `/отпуск`"
        )
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="📅 Мои отгулы", style=discord.ButtonStyle.secondary, row=1)
    async def my_dayoffs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ Это ваша панель.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        dayoffs = get_user_dayoffs(self.user_id)
        if not dayoffs:
            await interaction.followup.send("У вас пока нет отгулов.", ephemeral=True)
            return
        lines = ["**📋 Ваши отгулы:**"]
        for (date,) in dayoffs:
            lines.append(f"• {date}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @discord.ui.button(label="❌ Закрыть", style=discord.ButtonStyle.danger, row=2)
    async def close_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⛔ Это ваша панель.", ephemeral=True)
            return
        from commands.slash import active_help_messages
        if interaction.user.id in active_help_messages:
            del active_help_messages[interaction.user.id]
        await interaction.response.edit_message(content="❌ Панель закрыта.", embed=None, view=None)