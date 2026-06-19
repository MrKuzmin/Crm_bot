# ============================================================
# db/admins.py — работа с администраторами
# ============================================================

import sqlite3

from config import DB_NAME, SUPER_ADMIN_IDS


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


def is_super_admin(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT 1 FROM super_admins WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None


def add_super_admin(user_id: int):
    if user_id in SUPER_ADMIN_IDS:
        return
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT OR IGNORE INTO super_admins (user_id) VALUES (?)", (user_id,))
        conn.commit()


def remove_super_admin(user_id: int):
    if user_id in SUPER_ADMIN_IDS:
        return
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM super_admins WHERE user_id = ?", (user_id,))
        conn.commit()


def load_all_super_admins() -> list:
    result = list(SUPER_ADMIN_IDS)
    with sqlite3.connect(DB_NAME) as conn:
        for row in conn.execute("SELECT user_id FROM super_admins"):
            if row[0] not in SUPER_ADMIN_IDS:
                result.append(row[0])
    return result


def get_duty_admin() -> int:
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT admin_id FROM duty_admin LIMIT 1").fetchone()
        return row[0] if row else None


def set_duty_admin(admin_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM duty_admin")
        conn.execute("INSERT INTO duty_admin (admin_id) VALUES (?)", (admin_id,))
        conn.commit()


def remove_duty_admin():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM duty_admin")
        conn.commit()
