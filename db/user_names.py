# ============================================================
# db/user_names.py — кэширование имён пользователей
# ============================================================

import sqlite3
from config import DB_NAME


def _ensure_table():
    """Создаёт таблицу user_names, если её нет"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_names (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()


def save_user_name(user_id: int, display_name: str):
    """Сохраняет или обновляет имя пользователя в БД"""
    _ensure_table()
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO user_names (user_id, display_name, updated_at)
            VALUES (?, ?, datetime('now','localtime'))
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = excluded.display_name,
                updated_at = datetime('now','localtime')
        """, (user_id, display_name))
        conn.commit()


def get_cached_name(user_id: int) -> str | None:
    """Возвращает сохранённое имя пользователя, или None если нет"""
    _ensure_table()
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT display_name FROM user_names WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row[0] if row else None
