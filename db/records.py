# ============================================================
# db/records.py — записи пропусков, отработок, история
# ============================================================

import sqlite3

from config import DB_NAME, MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY


def get_hours_for_date(user_id: int, date: str, table: str) -> float:
    with sqlite3.connect(DB_NAME) as conn:
        result = conn.execute(
            f"SELECT COALESCE(SUM(hours), 0) FROM {table} WHERE user_id = ? AND date = ?",
            (user_id, date)
        ).fetchone()
    return result[0] if result else 0.0


def add_absence(user_id: int, date: str, hours: float):
    if hours <= 0:
        raise ValueError("Часы должны быть положительным числом")
    if hours > MAX_ABSENCE_PER_DAY:
        raise ValueError(f"Не более {MAX_ABSENCE_PER_DAY} часов пропуска в день")
    current = get_hours_for_date(user_id, date, "absences")
    if current + hours > MAX_ABSENCE_PER_DAY:
        raise ValueError(f"Суммарно не более {MAX_ABSENCE_PER_DAY} часов. Уже {current:.1f}ч")
    with sqlite3.connect(DB_NAME) as conn:
        from db.schema import now_db
        conn.execute(
            "INSERT INTO absences (user_id, date, hours, created_at) VALUES (?, ?, ?, ?)",
            (user_id, date, hours, now_db())
        )
        conn.commit()


def add_overtime(user_id: int, date: str, hours: float):
    if hours <= 0:
        raise ValueError("Часы должны быть положительным числом")
    if hours > MAX_OVERTIME_PER_DAY:
        raise ValueError(f"Не более {MAX_OVERTIME_PER_DAY} часов отработки в день")
    current = get_hours_for_date(user_id, date, "overtimes")
    if current + hours > MAX_OVERTIME_PER_DAY:
        raise ValueError(f"Суммарно не более {MAX_OVERTIME_PER_DAY} часов. Уже {current:.1f}ч")
    with sqlite3.connect(DB_NAME) as conn:
        from db.schema import now_db
        conn.execute(
            "INSERT INTO overtimes (user_id, date, hours, created_at) VALUES (?, ?, ?, ?)",
            (user_id, date, hours, now_db())
        )
        conn.commit()


def add_history(user_id: int, action: str, details: str = ""):
    with sqlite3.connect(DB_NAME) as conn:
        from db.schema import now_db
        conn.execute(
            "INSERT INTO history_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, action, details, now_db())
        )
        conn.commit()


def log_to_db(user_id: int, action: str, target_user_id: int = None, details: str = ""):
    with sqlite3.connect(DB_NAME) as conn:
        from db.schema import now_db
        conn.execute(
            "INSERT INTO log (user_id, action, target_user_id, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, action, target_user_id, details, now_db())
        )
        conn.commit()


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
        conn.execute("DELETE FROM dayoffs WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM history_log WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM log WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_names WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
