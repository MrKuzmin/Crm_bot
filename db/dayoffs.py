# ============================================================
# db/dayoffs.py — работа с отгулами
# ============================================================

import sqlite3

from config import DB_NAME


def get_last_dayoff(user_id: int) -> str:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT date FROM dayoffs WHERE user_id = ? AND status = 'approved' ORDER BY date DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        return row[0] if row else None


def add_dayoff(user_id: int, date: str, approved_by: int = None):
    status = 'approved' if approved_by is None else 'pending'
    with sqlite3.connect(DB_NAME) as conn:
        from db.schema import now_db
        cursor = conn.execute(
            "INSERT INTO dayoffs (user_id, date, status, approved_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, date, status, approved_by, now_db())
        )
        conn.commit()
        return cursor.lastrowid


def get_dayoff_by_id(dayoff_id: int) -> dict:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT id, user_id, date, status, approved_by FROM dayoffs WHERE id = ?",
            (dayoff_id,)
        ).fetchone()
        if row:
            return {"id": row[0], "user_id": row[1], "date": row[2], "status": row[3], "approved_by": row[4]}
    return None


def update_dayoff_status(dayoff_id: int, status: str, approved_by: int = None):
    with sqlite3.connect(DB_NAME) as conn:
        if approved_by:
            conn.execute("UPDATE dayoffs SET status = ?, approved_by = ? WHERE id = ?", (status, approved_by, dayoff_id))
        else:
            conn.execute("UPDATE dayoffs SET status = ? WHERE id = ?", (status, dayoff_id))
        conn.commit()


def check_existing_dayoff(user_id: int, date: str) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT id FROM dayoffs WHERE user_id = ? AND date = ? AND status != 'rejected'",
            (user_id, date)
        ).fetchone()
        return row is not None


def has_pending_dayoff(user_id: int) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT id FROM dayoffs WHERE user_id = ? AND status = 'pending'",
            (user_id,)
        ).fetchone()
        return row is not None


def get_user_dayoffs(user_id: int) -> list:
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT date FROM dayoffs WHERE user_id = ? AND status = 'approved' ORDER BY date DESC",
            (user_id,)
        ).fetchall()


def get_dayoffs_by_date(date: str) -> list:
    """Возвращает список user_id у кого отгул в указанную дату"""
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            "SELECT user_id FROM dayoffs WHERE date = ? AND status = 'approved'",
            (date,)
        ).fetchall()
        return [row[0] for row in rows]


def get_dayoffs_in_range(start_date: str, end_date: str) -> list:
    """Возвращает список (user_id, date) отгулов в диапазоне дат"""
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            "SELECT user_id, date FROM dayoffs WHERE date >= ? AND date <= ? AND status = 'approved' ORDER BY date",
            (start_date, end_date)
        ).fetchall()
        return [(row[0], row[1]) for row in rows]


def delete_dayoff(user_id: int, date: str) -> bool:
    """Удаляет отгул"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "DELETE FROM dayoffs WHERE user_id = ? AND date = ?",
            (user_id, date)
        )
        conn.commit()
        return cursor.rowcount > 0