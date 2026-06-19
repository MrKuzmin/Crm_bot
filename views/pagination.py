# ============================================================
# views/pagination.py — универсальная пагинация для длинных текстов
# ============================================================

import discord

from config import ITEMS_PER_PAGE


def get_page_count(total_items: int, items_per_page: int = ITEMS_PER_PAGE) -> int:
    """Возвращает количество страниц для заданного количества элементов"""
    if total_items <= 0:
        return 0
    return (total_items - 1) // items_per_page + 1


def split_into_pages(lines: list[str], max_chars: int = 1900) -> list[str]:
    """Разбивает список строк на страницы, каждая не длиннее max_chars символов"""
    pages = []
    current_page = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 за перевод строки
        if current_len + line_len > max_chars and current_page:
            pages.append("\n".join(current_page))
            current_page = []
            current_len = 0
        current_page.append(line)
        current_len += line_len

    if current_page:
        pages.append("\n".join(current_page))

    return pages if pages else [""]


class PaginationView(discord.ui.View):
    """View с кнопками ◀ ▶ для листания страниц"""

    def __init__(self, pages: list[str], timeout: int = 120):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current = 0
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_button.disabled = self.current == 0
        self.next_button.disabled = self.current >= len(self.pages) - 1
        self.page_label.label = f"📄 {self.current + 1}/{len(self.pages)}"

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(content=self.pages[self.current], view=self)

    @discord.ui.button(label="📄 1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # просто индикатор страницы

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        self._refresh_buttons()
        await interaction.response.edit_message(content=self.pages[self.current], view=self)


# Алиас для обратной совместимости
PaginatedView = PaginationView
