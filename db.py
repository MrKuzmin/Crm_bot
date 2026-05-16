# ============================================================
# db.py — вся работа с базой данных SQLite
# Таблицы: absences, overtimes, log, admins, history_log, vacations
# Никакой логики Discord — только данные
# ============================================================

import sqlite3
import csv
import io
from datetime import datetime, timezone, timedelta as td
from config import DB_NAME, SUPER_ADMIN_IDS

# Московское время для записи в БД
MSK = timezone(td(hours=3))

def now_db() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vacations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL,
                new_start_date TEXT,
                new_end_date TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
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
            "INSERT INTO absences (user_id, date, hours, created_at) VALUES (?, ?, ?, ?)",
            (user_id, date, hours, now_db())
        )
        conn.commit()


def add_overtime(user_id: int, date: str, hours: float):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO overtimes (user_id, date, hours, created_at) VALUES (?, ?, ?, ?)",
            (user_id, date, hours, now_db())
        )
        conn.commit()


def add_history(user_id: int, action: str, details: str = ""):
    """Записать событие в историю пользователя"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO history_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, action, details, now_db())
        )
        conn.commit()


# ============================================================
# Логика работы с отпусками
# ============================================================

def add_vacation_request(user_id: int, start_date: str, end_date: str, status: str) -> int:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "INSERT INTO vacations (user_id, start_date, end_date, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, start_date, end_date, status, now_db())
        )
        conn.commit()
        return cursor.lastrowid


def get_vacation_by_id(vac_id: int) -> dict:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT id, user_id, start_date, end_date, status, new_start_date, new_end_date FROM vacations WHERE id = ?",
            (vac_id,)
        ).fetchone()
        if row:
            return {
                "id": row[0], "user_id": row[1],
                "start_date": row[2], "end_date": row[3], "status": row[4],
                "new_start_date": row[5], "new_end_date": row[6]
            }
    return None


def check_existing_vacation(user_id: int, start_date: str, end_date: str) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT id FROM vacations WHERE user_id = ? AND start_date = ? AND end_date = ? AND status = 'approved'",
            (user_id, start_date, end_date)
        ).fetchone()
        return row is not None


def request_vacation_change(user_id: int, start_date: str, end_date: str, new_start: str, new_end: str) -> int:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "UPDATE vacations SET status = 'pending_change', new_start_date = ?, new_end_date = ? WHERE user_id = ? AND start_date = ? AND end_date = ? AND status = 'approved'",
            (new_start, new_end, user_id, start_date, end_date)
        )
        conn.commit()
        if cursor.rowcount > 0:
            row = conn.execute("SELECT id FROM vacations WHERE user_id = ? AND start_date = ? AND end_date = ?", (user_id, start_date, end_date)).fetchone()
            return row[0] if row else None
    return None


def update_vacation_status(vac_id: int, status: str):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE vacations SET status = ? WHERE id = ?", (status, vac_id))
        conn.commit()


def apply_vacation_change(vac_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "UPDATE vacations SET start_date = new_start_date, end_date = new_end_date, status = 'approved', new_start_date = NULL, new_end_date = NULL WHERE id = ?",
            (vac_id,)
        )
        conn.commit()


def admin_change_vacation(user_id: int, old_start: str, old_end: str, new_start: str, new_end: str) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "UPDATE vacations SET start_date = ?, end_date = ? WHERE user_id = ? AND start_date = ? AND end_date = ? AND status = 'approved'",
            (new_start, new_end, user_id, old_start, old_end)
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_vacation_db(user_id: int, start_date: str, end_date: str) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "DELETE FROM vacations WHERE user_id = ? AND start_date = ? AND end_date = ?",
            (user_id, start_date, end_date)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_all_active_vacations() -> list:
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT user_id, start_date, end_date FROM vacations WHERE status = 'approved' ORDER BY start_date ASC"
        ).fetchall()


def get_vacations_starting_today(date_str: str) -> list:
    """Находит все одобренные отпуска, начинающиеся на указанную дату"""
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT user_id, start_date, end_date FROM vacations WHERE status = 'approved' AND start_date = ?",
            (date_str,)
        ).fetchall()


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
        conn.execute("DELETE FROM vacations WHERE user_id = ?", (user_id,))
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
    cutoff = (datetime.now(MSK) - td(days=months * 30)).strftime("%Y-%m-%d")

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


# ============================================================
# Логирование
# ============================================================

def log_to_db(user_id: int, action: str, target_user_id: int = None, details: str = ""):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO log (user_id, action, target_user_id, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, action, target_user_id, details, now_db())
        )
        conn.commit()
    return f"[LOG] user={user_id} action={action} target={target_user_id} details={details}"