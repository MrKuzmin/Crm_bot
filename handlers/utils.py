# ============================================================
# handlers/utils.py — общие утилиты для обработчиков
# ============================================================

import re
from datetime import datetime, timezone, timedelta as td

from config import TIMEZONE_OFFSET, LOG_CHANNEL_ID
from db import get_absences, get_overtimes, get_balance, log_to_db

MSK = timezone(td(hours=TIMEZONE_OFFSET))


def now_msk() -> datetime:
    return datetime.now(MSK)


def today_msk() -> str:
    return now_msk().strftime("%d.%m.%Y")


def is_valid_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%d.%m.%y")
        return True
    except ValueError:
        try:
            datetime.strptime(date_str, "%d.%m.%Y")
            return True
        except ValueError:
            return False


def normalize_date(date_str: str) -> str:
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return date_str


def parse_date(text: str) -> str:
    text = text.lower().strip()
    today = now_msk()
    if text == "сегодня":
        return today.strftime("%d.%m.%Y")
    elif text == "вчера":
        return (today - td(days=1)).strftime("%d.%m.%Y")
    elif text == "завтра":
        return (today + td(days=1)).strftime("%d.%m.%Y")
    elif is_valid_date(text):
        return normalize_date(text)
    return None


def extract_mention(content: str):
    match = re.search(r'<@!?(\d+)>', content)
    return int(match.group(1)) if match else None


def extract_department(display_name: str) -> str:
    match = re.search(r'\[([^\]]+)\]', display_name)
    return match.group(1) if match else "Общий"


async def find_user(query: str, bot):
    if not query:
        return None
    uid = extract_mention(query)
    if uid:
        user = await get_user_by_id(uid, bot)
        if user:
            return user
    if query.isdigit():
        user = await get_user_by_id(int(query), bot)
        if user:
            return user
    for guild in bot.guilds:
        for member in guild.members:
            if member.name.lower() == query.lower():
                return member
            if member.display_name.lower() == query.lower():
                return member
            if str(member).lower() == query.lower():
                return member
    for guild in bot.guilds:
        for member in guild.members:
            if query.lower() in member.name.lower() or query.lower() in member.display_name.lower():
                return member
    return None


async def get_user_by_id(user_id: int, bot):
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member:
            return member
    try:
        return await bot.fetch_user(user_id)
    except:
        return None


def is_admin(user_id: int, current_admins: list) -> bool:
    return user_id in current_admins


def format_status(user_id: int, user_name: str) -> str:
    absences = get_absences(user_id)
    overtimes = get_overtimes(user_id)
    balance = get_balance(user_id)
    lines = [f"📊 **Статус: {user_name}**\n"]
    if absences:
        lines.append("🔴 **Долги:**")
        for date, hours in absences:
            lines.append(f"• {date} — {hours:.2f} ч")
    else:
        lines.append("🔴 **Долги:** нет")
    lines.append("")
    if overtimes:
        lines.append("🟢 **Отработано:**")
        for date, hours in overtimes:
            lines.append(f"• {date} — {hours:.2f} ч")
    else:
        lines.append("🟢 **Отработано:** нет")
    lines.append("")
    if balance > 0:
        lines.append(f"❌ **Нужно отработать: {balance:.2f} ч**")
    elif balance == 0:
        lines.append("✅ **У вас нет долгов.**")
    else:
        lines.append(f"🟢 **У вас переработка: {abs(balance):.2f} ч**")
    return "\n".join(lines)


async def send_log(action: str, user_id: int, target_user_id: int, details: str, bot):
    log_line = log_to_db(user_id, action, target_user_id, details)
    print(log_line)
    if LOG_CHANNEL_ID and LOG_CHANNEL_ID != 0:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.send(f"`{log_line}`")
            except:
                pass