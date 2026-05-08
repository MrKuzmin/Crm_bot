# ============================================================
# db.py — вся работа с базой данных SQLite
# Таблицы: absences, overtimes, log, admins, history_log
# Никакой логики Discord — только данные
# ============================================================

import sqlite3
import csv
import io
from datetime import datetime, timedelta as td
from config import DB_NAME, SUPER_ADMIN_IDS


# ============================================================
# Инициализация базы данных
# ============================================================

def init_db():
    """Создаёт все таблицы, если их ещё нет"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                hours REAL NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS overtimes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                hours REAL NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_user_id INTEGER,
                details TEXT,
                timestamp TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                timestamp TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()


# ============================================================
# Работа с админами
# ============================================================

def load_all_admins() -> list:
    admins = set(SUPER_ADMIN_IDS)
    with sqlite3.connect(DB_NAME) as conn:
        for row in conn.execute("SELECT user_id FROM admins"):
            admins.add(row[0])
    return list(admins)


def add_admin_to_db(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()


def remove_admin_from_db(user_id: int):
    if user_id in SUPER_ADMIN_IDS:
        return
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()


# ============================================================
# Добавление записей
# ============================================================

def add_absence(user_id: int, date: str, hours: float):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO absences (user_id, date, hours) VALUES (?, ?, ?)",
            (user_id, date, hours)
        )
        conn.commit()


def add_overtime(user_id: int, date: str, hours: float):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO overtimes (user_id, date, hours) VALUES (?, ?, ?)",
            (user_id, date, hours)
        )
        conn.commit()


def add_history(user_id: int, action: str, details: str = ""):
    """Записать событие в историю пользователя (удаление, обнуление, увольнение)"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO history_log (user_id, action, details) VALUES (?, ?, ?)",
            (user_id, action, details)
        )
        conn.commit()


# ============================================================
# Удаление записей
# ============================================================

def delete_absence(user_id: int, date: str) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "DELETE FROM absences WHERE user_id = ? AND date = ?",
            (user_id, date)
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_overtime(user_id: int, date: str) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "DELETE FROM overtimes WHERE user_id = ? AND date = ?",
            (user_id, date)
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_all_user_records(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM absences WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM overtimes WHERE user_id = ?", (user_id,))
        conn.commit()


# ============================================================
# Получение данных
# ============================================================

def get_absences(user_id: int) -> list:
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT date, hours FROM absences WHERE user_id = ? ORDER BY date ASC",
            (user_id,)
        ).fetchall()


def get_overtimes(user_id: int) -> list:
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT date, hours FROM overtimes WHERE user_id = ? ORDER BY date ASC",
            (user_id,)
        ).fetchall()


def get_balance(user_id: int) -> float:
    with sqlite3.connect(DB_NAME) as conn:
        abs_sum = conn.execute(
            "SELECT COALESCE(SUM(hours), 0) FROM absences WHERE user_id = ?",
            (user_id,)
        ).fetchone()[0]
        ovt_sum = conn.execute(
            "SELECT COALESCE(SUM(hours), 0) FROM overtimes WHERE user_id = ?",
            (user_id,)
        ).fetchone()[0]
    return abs_sum - ovt_sum


def get_hours_for_date(user_id: int, date: str, table: str) -> float:
    with sqlite3.connect(DB_NAME) as conn:
        result = conn.execute(
            f"SELECT COALESCE(SUM(hours), 0) FROM {table} WHERE user_id = ? AND date = ?",
            (user_id, date)
        ).fetchone()
    return result[0] if result else 0.0


def get_all_debtors() -> list:
    with sqlite3.connect(DB_NAME) as conn:
        users = set()
        for row in conn.execute("SELECT DISTINCT user_id FROM absences"):
            users.add(row[0])
        for row in conn.execute("SELECT DISTINCT user_id FROM overtimes"):
            users.add(row[0])
    debtors = []
    for uid in users:
        balance = get_balance(uid)
        if balance > 0:
            debtors.append((uid, balance))
    return sorted(debtors, key=lambda x: x[1], reverse=True)


def get_full_history(user_id: int) -> list:
    """Все записи: пропуски + отработки + история удалений/обнулений"""
    with sqlite3.connect(DB_NAME) as conn:
        absences = conn.execute(
            "SELECT date, hours, 'пропуск' as type FROM absences WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        overtimes = conn.execute(
            "SELECT date, hours, 'отработка' as type FROM overtimes WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        history = conn.execute(
            "SELECT timestamp, 0, action FROM history_log WHERE user_id = ?",
            (user_id,)
        ).fetchall()

    all_records = [(r[0], r[1], r[2]) for r in absences + overtimes]
    for timestamp, _, action in history:
        all_records.append((timestamp[:10], 0, f"⚡ {action}"))

    return sorted(all_records, key=lambda r: r[0])


# ============================================================
# Экспорт в CSV
# ============================================================

def export_user_csv(user_id: int, months: int = 1) -> tuple:
    """Экспорт записей пользователя за N месяцев в CSV"""
    records = get_full_history(user_id)
    cutoff = (datetime.now() - td(days=months * 30)).strftime("%Y-%m-%d")

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
    filename = f"otchet_{user_id}_{datetime.now().strftime('%Y-%m-%d')}_{months}mes.csv"

    return filename, csv_bytes


# ============================================================
# Логирование
# ============================================================

def log_to_db(user_id: int, action: str, target_user_id: int = None, details: str = ""):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO log (user_id, action, target_user_id, details) VALUES (?, ?, ?, ?)",
            (user_id, action, target_user_id, details)
        )
        conn.commit()
    return f"[LOG] user={user_id} action={action} target={target_user_id} details={details}"