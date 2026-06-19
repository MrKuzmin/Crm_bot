# ============================================================
# db/reports.py — отчёты и экспорт
# ============================================================

import csv
import io
import sqlite3
from datetime import datetime, timezone, timedelta as td

from config import DB_NAME

MSK = timezone(td(hours=3))


def export_user_csv(user_id: int, months: int = 1) -> tuple:
    from db.records import get_full_history, get_balance
    cutoff = (datetime.now(MSK) - td(days=months * 30)).strftime("%Y-%m-%d")

    records = get_full_history(user_id)
    filtered = [
        (date, hours, rtype) for date, hours, rtype in records
        if not rtype.startswith("⚡") and date >= cutoff
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата", "Тип", "Часы"])

    for date, hours, rtype in filtered:
        writer.writerow([date, rtype, f"{hours:.2f}"])

    balance = get_balance(user_id)
    if balance > 0:
        itog = f"Долг: {balance:.2f} ч"
    elif balance == 0:
        itog = "Долгов нет"
    else:
        itog = f"Переработка: {abs(balance):.2f} ч"
    writer.writerow([])
    writer.writerow(["Итог", itog, ""])

    csv_bytes = output.getvalue().encode('utf-8-sig')
    filename = f"otchet_{user_id}_{datetime.now(MSK).strftime('%Y-%m-%d')}_{months}mes.csv"

    return filename, csv_bytes


def export_full_report(months: int = 1) -> tuple:
    from db.records import get_balance
    cutoff = (datetime.now(MSK) - td(days=months * 30)).strftime("%Y-%m-%d")

    with sqlite3.connect(DB_NAME) as conn:
        users = set()
        for row in conn.execute("SELECT DISTINCT user_id FROM absences"):
            users.add(row[0])
        for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
            users.add(row[0])
        for row in conn.execute("SELECT DISTINCT user_id FROM dayoffs"):
            users.add(row[0])
        for row in conn.execute("SELECT DISTINCT user_id FROM vacations"):
            users.add(row[0])

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    writer.writerow([
        "ID пользователя",
        "Пропуски (часы)", "Пропуски (даты)",
        "Отработки (часы)", "Отработки (даты)",
        "Баланс",
        "Отгулы (даты)",
        "Отпуска (периоды)",
        "История действий"
    ])

    for uid in sorted(users):
        absences = conn.execute(
            "SELECT date, hours FROM absences WHERE user_id = ? AND date >= ? ORDER BY date ASC",
            (uid, cutoff)
        ).fetchall()

        overtimes = conn.execute(
            "SELECT date, hours FROM overtimes WHERE user_id = ? AND date >= ? ORDER BY date ASC",
            (uid, cutoff)
        ).fetchall()

        dayoffs = conn.execute(
            "SELECT date FROM dayoffs WHERE user_id = ? AND status = 'approved' AND date >= ? ORDER BY date ASC",
            (uid, cutoff)
        ).fetchall()

        vacations = conn.execute(
            "SELECT start_date, end_date FROM vacations WHERE status = 'approved' AND user_id = ? AND start_date >= ? ORDER BY start_date ASC",
            (uid, cutoff)
        ).fetchall()

        history = conn.execute(
            "SELECT timestamp, action, details FROM history_log WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp ASC",
            (uid, cutoff)
        ).fetchall()

        abs_sum = sum(h for _, h in absences)
        ovt_sum = sum(h for _, h in overtimes)
        balance = abs_sum - ovt_sum

        abs_dates = "; ".join([f"{d}({h:.1f})" for d, h in absences]) if absences else "-"
        ovt_dates = "; ".join([f"{d}({h:.1f})" for d, h in overtimes]) if overtimes else "-"
        dayoff_dates = "; ".join([d for (d,) in dayoffs]) if dayoffs else "-"
        vacation_periods = "; ".join([f"{s}-{e}" for s, e in vacations]) if vacations else "-"
        history_actions = "; ".join([f"{ts[:10]} {a}" for ts, a, _ in history[:10]]) if history else "-"
        if len(history) > 10:
            history_actions += f"... и ещё {len(history)-10}"

        writer.writerow([
            uid,
            f"{abs_sum:.2f}", abs_dates,
            f"{ovt_sum:.2f}", ovt_dates,
            f"{balance:.2f}",
            dayoff_dates,
            vacation_periods,
            history_actions
        ])

    csv_bytes = output.getvalue().encode('utf-8-sig')
    filename = f"full_report_{datetime.now(MSK).strftime('%Y-%m-%d')}_{months}mes.csv"

    return filename, csv_bytes
