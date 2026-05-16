# ============================================================
# handlers/vacation_handler.py — всё, что связано с отпусками
# ============================================================

import re
import sqlite3
from datetime import datetime

import discord

from config import DB_NAME, MAX_VACATION_DAYS_PER_YEAR, SUPER_ADMIN_IDS
from db import (
    add_vacation_request, get_vacation_by_id, check_existing_vacation,
    request_vacation_change, update_vacation_status, apply_vacation_change,
    admin_change_vacation, delete_vacation_db, get_all_active_vacations,
    get_vacation_days_for_year
)
from .utils import (
    now_msk, is_valid_date, normalize_date,
    extract_department, find_user, get_user_by_id, is_admin, send_log
)


async def handle_vacation_command(message: discord.Message, bot, current_admins: list, vacation_view_class):
    """Точка входа для всех команд, связанных с отпусками"""
    content = message.content.strip()
    user_id = message.author.id

    if content.lower().startswith("изменить отпуск"):
        return await _handle_vacation_change(message, bot, current_admins, vacation_view_class)

    if content.lower() == "мои отпуска":
        return await _cmd_my_vacations(message, user_id, bot)

    if content.lower() == "статус отпусков":
        return await _cmd_vacation_status(message, bot, current_admins)

    if content.lower().startswith("отпуск"):
        return await _handle_vacation_create(message, bot, current_admins, vacation_view_class)


async def _cmd_my_vacations(message: discord.Message, user_id: int, bot):
    """Показывает отпуска сотрудника и его отдела"""
    vacations = get_all_active_vacations()

    member = await get_user_by_id(user_id, bot)
    my_dept = extract_department(member.display_name).lower() if member else "общий"

    filtered = []
    for uid, s_date, e_date in vacations:
        m = await get_user_by_id(uid, bot)
        dept = extract_department(m.display_name).lower() if m else "общий"
        if dept == my_dept:
            filtered.append((uid, s_date, e_date, m.display_name if m else f"ID:{uid}"))

    table_lines = ["```", f"📋 ГРАФИК ОТПУСКОВ ОТДЕЛА {my_dept.upper()} И ВАШ СТАТУС", "=" * 52]
    table_lines.append(f"{'Сотрудник':<32} | {'Начало':<10} | {'Окончание':<10}")
    table_lines.append("-" * 54)

    if not filtered:
        table_lines.append(f"В отделе {my_dept.upper()} активных отпусков нет.")
    else:
        for uid, s_date, e_date, display_name in filtered:
            marker = " (Вы)" if uid == user_id else ""
            full = f"{display_name}{marker}"
            if len(full) > 32:
                full = full[:29] + "..."
            table_lines.append(f"{full:<32} | {s_date:<10} | {e_date:<10}")

    table_lines.append("```")
    await message.channel.send("\n".join(table_lines))


async def _cmd_vacation_status(message: discord.Message, bot, current_admins: list):
    """Сводка отпусков по отделам (только админ)"""
    if not is_admin(message.author.id, current_admins):
        await message.channel.send("⛔ Только администратор имеет доступ к этой команде.")
        return

    vacations = get_all_active_vacations()
    by_dept = {}
    for uid, s_date, e_date in vacations:
        member = await get_user_by_id(uid, bot)
        name = member.display_name if member else f"ID:{uid}"
        dept = extract_department(name).lower()
        if dept not in by_dept:
            by_dept[dept] = []
        by_dept[dept].append((name, s_date, e_date))

    if not by_dept:
        await message.channel.send("📋 В системе нет утвержденных неотгуленных отпусков.")
        return

    msg_parts = ["📊 **Сводный статус отпусков компании по отделам:**\n"]
    for dept, vac_list in by_dept.items():
        msg_parts.append(f"📁 **Отдел: {dept}**")
        msg_parts.append("```")
        msg_parts.append(f"{'Сотрудник':<32} | {'Дата начала':<12} | {'Дата окончания':<12}")
        msg_parts.append("-" * 60)
        for name, s_date, e_date in vac_list:
            if len(name) > 32:
                name = name[:29] + "..."
            msg_parts.append(f"{name:<32} | {s_date:<12} | {e_date:<12}")
        msg_parts.append("```\n")

    await message.channel.send("\n".join(msg_parts))


async def _handle_vacation_create(message: discord.Message, bot, current_admins: list, vacation_view_class):
    """Оформление нового отпуска"""
    content = message.content.strip()
    user_id = message.author.id

    date_match = re.search(r'([0-9.]{6,10})-([0-9.]{6,10})', content)
    if not date_match:
        await message.channel.send(
            "🌴 **Управление отпусками в Crm_Bot**\n\n"
            "**Пользовательские команды:**\n"
            "• `отпуск ДД.ММ.ГГ-ДД.ММ.ГГ` — отправить заявку\n"
            "• `мои отпуска` — график отпусков\n"
            "• `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на ДД.ММ.ГГ-ДД.ММ.ГГ` — перенос\n"
            "• `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на 0` — удаление\n\n"
            "**Админские команды:**\n"
            "• `отпуск ДД.ММ.ГГ-ДД.ММ.ГГ @Юзер` — назначить\n"
            "• `статус отпусков` — сводка по отделам"
        )
        return

    start_date = normalize_date(date_match.group(1))
    end_date = normalize_date(date_match.group(2))

    if not is_valid_date(start_date) or not is_valid_date(end_date):
        await message.channel.send("❌ Неверный формат дат! Пишите в виде: `отпуск 01.06.26-14.06.26`")
        return

    query_for_user = content[date_match.end():].strip()
    target_user = None
    admin_mode = False

    if query_for_user:
        target_user = await find_user(query_for_user, bot)
        if target_user:
            if not is_admin(user_id, current_admins):
                await message.channel.send("⛔ Только админ может напрямую назначать отпуска сотрудникам.")
                return
            admin_mode = True
        else:
            await message.channel.send(f"❌ Пользователь `{query_for_user}` не найден.")
            return
    else:
        target_user = message.author
        if is_admin(user_id, current_admins):
            admin_mode = True

    # Парсим даты для проверок
    try:
        d1 = datetime.strptime(start_date, "%d.%m.%Y")
        d2 = datetime.strptime(end_date, "%d.%m.%Y")
        new_days = (d2 - d1).days + 1
    except:
        await message.channel.send("❌ Ошибка расчёта дней отпуска.")
        return

    # Проверка: даты не в прошлом (кроме суперадмина)
    if user_id not in SUPER_ADMIN_IDS:
        today = datetime.now()
        if d1.date() < today.date():
            await message.channel.send("❌ Нельзя создать отпуск с датой начала в прошлом.")
            return

    # Проверка: пересечение с существующими отпусками
    existing = get_all_active_vacations()
    for uid, s, e in existing:
        if uid == target_user.id:
            try:
                exist_d1 = datetime.strptime(s, "%d.%m.%Y")
                exist_d2 = datetime.strptime(e, "%d.%m.%Y")
                if not (d2 < exist_d1 or d1 > exist_d2):
                    await message.channel.send(
                        f"❌ Даты пересекаются с уже утверждённым отпуском {target_user.display_name}: {s} - {e}."
                    )
                    return
            except:
                pass

    # Проверка лимита дней в году
    year = d1.year
    used = get_vacation_days_for_year(target_user.id, year)
    if used + new_days > MAX_VACATION_DAYS_PER_YEAR:
        await message.channel.send(
            f"❌ Нельзя назначить {new_days} дн. отпуска. "
            f"У {target_user.display_name} уже использовано {used:.0f} дн. из {MAX_VACATION_DAYS_PER_YEAR} за {year} год."
        )
        return

    if admin_mode:
        add_vacation_request(target_user.id, start_date, end_date, "approved")
        await message.channel.send(
            f"✅ Административный отпуск для {target_user.display_name} успешно создан на период `{start_date} - {end_date}`."
        )
        if target_user.id != user_id:
            try:
                await target_user.send(
                    f"💼 Администратор напрямую утвердил вам отпуск в период с **{start_date}** по **{end_date}**."
                )
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[WARN] Не удалось отправить ЛС об утверждении отпуска: {e}")
        await send_log("admin_add_vacation", user_id, target_user.id, f"dates={start_date}-{end_date}", bot)
    else:
        vac_id = add_vacation_request(user_id, start_date, end_date, "pending_approval")

        for admin_id in current_admins:
            admin_user = await get_user_by_id(admin_id, bot)
            if admin_user and admin_id != user_id:
                view = vacation_view_class(vac_id)
                try:
                    await admin_user.send(
                        f"🔔 **Новая заявка на отпуск!**\n"
                        f"От: {message.author.mention}\n"
                        f"Период: **{start_date} - {end_date}**",
                        view=view
                    )
                except discord.Forbidden:
                    pass
                except Exception as e:
                    print(f"[WARN] Не удалось отправить заявку админу {admin_id}: {e}")
        await message.channel.send(
            f"✉️ Заявка на отпуск с `{start_date}` по `{end_date}` отправлена руководству. Ожидайте подтверждения."
        )


async def _handle_vacation_change(message: discord.Message, bot, current_admins: list, vacation_view_class):
    """Изменение или удаление существующего отпуска"""
    content = message.content.strip()
    user_id = message.author.id

    date_match = re.search(r'([0-9.]{6,10})-([0-9.]{6,10})\s+на\s+([0-9.]{6,10}|0)', content)
    if not date_match:
        await message.channel.send(
            "❌ Формат: `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на ДД.ММ.ГГ-ДД.ММ.ГГ` "
            "или `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на 0`"
        )
        return

    old_start = normalize_date(date_match.group(1))
    old_end = normalize_date(date_match.group(2))
    val_on = date_match.group(3)
    is_delete = val_on == "0"

    after_dates = content[date_match.end():].strip()

    if is_delete:
        query_for_user = re.sub(r'^0\s*', '', after_dates).strip()
        new_start = new_end = None
    else:
        new_match = re.search(r'([0-9.]{6,10})-([0-9.]{6,10})', after_dates)
        if new_match:
            new_start = normalize_date(new_match.group(1))
            new_end = normalize_date(new_match.group(2))
            query_for_user = after_dates[new_match.end():].strip()
        else:
            await message.channel.send("❌ Укажите новые даты: `изменить отпуск ДД.ММ.ГГ-ДД.ММ.ГГ на ДД.ММ.ГГ-ДД.ММ.ГГ`")
            return

    target_user = None
    admin_mode = False

    if query_for_user:
        target_user = await find_user(query_for_user, bot)
        if target_user:
            if not is_admin(user_id, current_admins):
                await message.channel.send("⛔ Только админ может менять отпуска других сотрудников.")
                return
            admin_mode = True
        else:
            await message.channel.send(f"❌ Пользователь `{query_for_user}` не найден.")
            return
    else:
        target_user = message.author
        if is_admin(user_id, current_admins):
            admin_mode = True

    if not is_valid_date(old_start) or not is_valid_date(old_end):
        await message.channel.send("❌ Существующие даты отпуска указаны неверно.")
        return
    if not is_delete and (not is_valid_date(new_start) or not is_valid_date(new_end)):
        await message.channel.send("❌ Новые даты отпуска указаны в неверном формате.")
        return
    if not check_existing_vacation(target_user.id, old_start, old_end):
        await message.channel.send(
            f"❌ Существующий отпуск с {old_start} по {old_end} у пользователя {target_user.display_name} не найден в базе!"
        )
        return

    # Проверки при изменении
    if not is_delete:
        try:
            d1 = datetime.strptime(new_start, "%d.%m.%Y")
            d2 = datetime.strptime(new_end, "%d.%m.%Y")
            new_days = (d2 - d1).days + 1
            old_d1 = datetime.strptime(old_start, "%d.%m.%Y")
            old_d2 = datetime.strptime(old_end, "%d.%m.%Y")
            old_days = (old_d2 - old_d1).days + 1
        except:
            await message.channel.send("❌ Ошибка расчёта дней отпуска.")
            return

        # Проверка: даты не в прошлом (кроме суперадмина)
        if user_id not in SUPER_ADMIN_IDS:
            today = datetime.now()
            if d1.date() < today.date():
                await message.channel.send("❌ Нельзя перенести отпуск на дату в прошлом.")
                return

        # Проверка: пересечение с другими отпусками (исключая текущий)
        existing = get_all_active_vacations()
        for uid, s, e in existing:
            if uid == target_user.id:
                try:
                    exist_d1 = datetime.strptime(s, "%d.%m.%Y")
                    exist_d2 = datetime.strptime(e, "%d.%m.%Y")
                    # Пропускаем тот же самый отпуск
                    if s == old_start and e == old_end:
                        continue
                    if not (d2 < exist_d1 or d1 > exist_d2):
                        await message.channel.send(
                            f"❌ Новые даты пересекаются с другим отпуском {target_user.display_name}: {s} - {e}."
                        )
                        return
                except:
                    pass

        # Проверка лимита дней в году
        year = d1.year
        used = get_vacation_days_for_year(target_user.id, year)
        available = MAX_VACATION_DAYS_PER_YEAR - (used - old_days)
        if new_days > available:
            await message.channel.send(
                f"❌ Нельзя изменить на {new_days} дн. "
                f"У {target_user.display_name} доступно только {available:.0f} дн. из {MAX_VACATION_DAYS_PER_YEAR} за {year} год."
            )
            return

    if admin_mode:
        if is_delete:
            delete_vacation_db(target_user.id, old_start, old_end)
            await message.channel.send(f"🗑️ Админ удалил отпуск для {target_user.display_name} ({old_start} - {old_end}).")
            try:
                await target_user.send(f"🗑️ Администратор удалил ваш отпуск с {old_start} по {old_end}.")
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[WARN] Не удалось отправить ЛС об удалении отпуска: {e}")
        else:
            admin_change_vacation(target_user.id, old_start, old_end, new_start, new_end)
            await message.channel.send(
                f"🔄 Админ изменил даты отпуска для {target_user.display_name} на {new_start} - {new_end}."
            )
            try:
                await target_user.send(
                    f"🔄 Администратор изменил даты вашего отпуска с ({old_start} - {old_end}) "
                    f"на новые: **{new_start} - {new_end}**."
                )
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[WARN] Не удалось отправить ЛС об изменении отпуска: {e}")
        await send_log("admin_vacation_change", user_id, target_user.id, f"delete={is_delete}", bot)
    else:
        if is_delete:
            vac_id = add_vacation_request(user_id, old_start, old_end, "pending_approval")
            update_vacation_status(vac_id, "pending_approval")
            for admin_id in current_admins:
                admin_user = await get_user_by_id(admin_id, bot)
                if admin_user and admin_id != user_id:
                    view = vacation_view_class(vac_id)
                    try:
                        await admin_user.send(
                            f"🚨 **Запрос на УДАЛЕНИЕ отпуска!**\n"
                            f"Сотрудник: {message.author.mention}\n"
                            f"Удалить отпуск: с {old_start} по {old_end}",
                            view=view
                        )
                    except discord.Forbidden:
                        pass
                    except Exception as e:
                        print(f"[WARN] Не удалось отправить заявку на удаление админу {admin_id}: {e}")
            await message.channel.send("✉️ Заявка на удаление отпуска успешно отправлена администраторам на подтверждение.")
        else:
            vac_id = request_vacation_change(user_id, old_start, old_end, new_start, new_end)
            if not vac_id:
                await message.channel.send("❌ Ошибка при формировании заявки на перенос.")
                return
            for admin_id in current_admins:
                admin_user = await get_user_by_id(admin_id, bot)
                if admin_user and admin_id != user_id:
                    view = vacation_view_class(vac_id)
                    try:
                        await admin_user.send(
                            f"🚨 **Запрос на ИЗМЕНЕНИЕ отпуска!**\n"
                            f"Сотрудник: {message.author.mention}\n"
                            f"Старые даты: {old_start} - {old_end}\n"
                            f"Новые даты: **{new_start} - {new_end}**",
                            view=view
                        )
                    except discord.Forbidden:
                        pass
                    except Exception as e:
                        print(f"[WARN] Не удалось отправить заявку на изменение админу {admin_id}: {e}")
            await message.channel.send(
                f"✉️ Заявка на перенос отпуска с {old_start} на новые даты **{new_start} - {new_end}** отправлена админам."
            )