# ============================================================
# db/vacations.py — работа с отпусками
# ============================================================

import sqlite3
from datetime import datetime, timezone, timedelta as td

from config import DB_NAME, MAX_VACATION_DAYS_PER_YEAR

MSK = timezone(td(hours=3))


def add_vacation_request(user_id: int, start_date: str, end_date: str, status: str) -> int:
    # Проверка лимита отпускных дней — только для утверждённых отпусков
    if status == "approved":
        try:
            d1 = datetime.strptime(start_date, "%d.%m.%Y")
            d2 = datetime.strptime(end_date, "%d.%m.%Y")
        except ValueError:
            raise ValueError("Неверный формат даты")
        requested_days = (d2 - d1).days + 1
        if requested_days <= 0:
            raise ValueError("Дата окончания не может быть раньше даты начала")
        # Проверяем каждый календарный год, который затрагивает отпуск
        for y in range(d1.year, d2.year + 1):
            year_start = datetime(y, 1, 1)
            year_end = datetime(y, 12, 31)
            start = max(d1, year_start)
            end = min(d2, year_end)
            if start <= end:
                days_in_year = (end - start).days + 1
                existing = get_vacation_days_for_year(user_id, y)
                if existing + days_in_year > MAX_VACATION_DAYS_PER_YEAR:
                    raise ValueError(
                        f"Превышен лимит отпускных дней в {y} году "
                        f"({MAX_VACATION_DAYS_PER_YEAR}). "
                        f"Уже использовано: {existing:.0f}, запрошено: {days_in_year:.0f}"
                    )
    with sqlite3.connect(DB_NAME) as conn:
        from db.schema import now_db
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
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT user_id, start_date, end_date FROM vacations WHERE status = 'approved' AND start_date = ?",
            (date_str,)
        ).fetchall()


def get_vacation_days_for_year(user_id: int, year: int) -> float:
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            "SELECT start_date, end_date FROM vacations WHERE user_id = ? AND status = 'approved'",
            (user_id,)
        ).fetchall()

    total = 0.0
    for s, e in rows:
        try:
            d1 = datetime.strptime(s, "%d.%m.%Y")
            d2 = datetime.strptime(e, "%d.%m.%Y")
            year_start = datetime(year, 1, 1)
            year_end = datetime(year, 12, 31)
            start = max(d1, year_start)
            end = min(d2, year_end)
            if start <= end:
                total += (end - start).days + 1
        except Exception:
            pass
    return total


def count_pending_vacations(user_id: int) -> int:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM vacations WHERE user_id = ? AND status IN ('pending_approval', 'pending_change')",
            (user_id,)
        ).fetchone()
        return row[0] if row else 0
