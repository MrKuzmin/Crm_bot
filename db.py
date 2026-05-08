# ============================================================
# db.py — вся работа с базой данных SQLite
# Таблицы: absences, overtimes, log, admins
# Никакой логики Discord — только данные
# ============================================================

import sqlite3
import csv
import io
from datetime import datetime
from config import DB_NAME, SUPER_ADMIN_IDS


# ============================================================
# Инициализация базы данных (вызывается при старте бота)
# ============================================================

def init_db():
    """Создаёт все таблицы, если их ещё нет"""
    with sqlite3.connect(DB_NAME) as conn:
        # Пропуски: кто, когда, на сколько часов
        conn.execute("""
            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                hours REAL NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        # Отработки: кто, когда, на сколько часов
        conn.execute("""
            CREATE TABLE IF NOT EXISTS overtimes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                hours REAL NOT NULL,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        # Логи: кто и какое действие совершил
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
        # Админы: ID тех, кто получил права через ключ
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()


# ============================================================
# Работа с админами
# ============================================================

def load_all_admins() -> list:
    """
    Загружает полный список админов:
    суперадмин из кода + все из таблицы admins
    """
    admins = set(SUPER_ADMIN_IDS)  # Суперадмин всегда
    with sqlite3.connect(DB_NAME) as conn:
        for row in conn.execute("SELECT user_id FROM admins"):
            admins.add(row[0])
    return list(admins)


def add_admin_to_db(user_id: int):
    """Добавляет пользователя в таблицу админов"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()


def remove_admin_from_db(user_id: int):
    """
    Убирает пользователя из таблицы админов.
    Суперадмина удалить нельзя — просто молча выходим.
    """
    if user_id in SUPER_ADMIN_IDS:
        return
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()


# ============================================================
# Добавление записей (пропуски и отработки)
# ============================================================

def add_absence(user_id: int, date: str, hours: float):
    """Записать пропуск в базу"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO absences (user_id, date, hours) VALUES (?, ?, ?)",
            (user_id, date, hours)
        )
        conn.commit()


def add_overtime(user_id: int, date: str, hours: float):
    """Записать отработку в базу"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO overtimes (user_id, date, hours) VALUES (?, ?, ?)",
            (user_id, date, hours)
        )
        conn.commit()


# ============================================================
# Удаление записей
# ============================================================

def delete_absence(user_id: int, date: str) -> bool:
    """
    Удалить пропуск пользователя за указанную дату.
    Возвращает True, если запись была и удалена.
    """
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "DELETE FROM absences WHERE user_id = ? AND date = ?",
            (user_id, date)
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_overtime(user_id: int, date: str) -> bool:
    """
    Удалить отработку пользователя за указанную дату.
    Возвращает True, если запись была и удалена.
    """
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "DELETE FROM overtimes WHERE user_id = ? AND date = ?",
            (user_id, date)
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_all_user_records(user_id: int):
    """
    Удалить ВСЕ записи пользователя (увольнение).
    Пропуски и отработки — всё стирается.
    """
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM absences WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM overtimes WHERE user_id = ?", (user_id,))
        conn.commit()


# ============================================================
# Получение данных (для статуса, отчётов, истории)
# ============================================================

def get_absences(user_id: int) -> list:
    """Все пропуски пользователя: список (дата, часы)"""
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT date, hours FROM absences WHERE user_id = ? ORDER BY date ASC",
            (user_id,)
        ).fetchall()


def get_overtimes(user_id: int) -> list:
    """Все отработки пользователя: список (дата, часы)"""
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(
            "SELECT date, hours FROM overtimes WHERE user_id = ? ORDER BY date ASC",
            (user_id,)
        ).fetchall()


def get_balance(user_id: int) -> float:
    """
    Баланс пользователя по формуле: пропуски − отработки.
    > 0 → должен отработать
    = 0 → долгов нет
    < 0 → переработка
    """
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
    """
    Сколько часов уже записано за конкретную дату.
    table = "absences" или "overtimes".
    Нужно для проверки лимитов.
    """
    with sqlite3.connect(DB_NAME) as conn:
        result = conn.execute(
            f"SELECT COALESCE(SUM(hours), 0) FROM {table} WHERE user_id = ? AND date = ?",
            (user_id, date)
        ).fetchone()
    return result[0] if result else 0.0


def get_all_debtors() -> list:
    """
    Все, у кого баланс > 0.
    Возвращает список (user_id, долг), отсортированный по убыванию долга.
    """
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
    """
    Все записи пользователя: пропуски + отработки.
    Возвращает список (дата, часы, тип) отсортированный по дате.
    """
    with sqlite3.connect(DB_NAME) as conn:
        absences = conn.execute(
            "SELECT date, hours, 'пропуск' as type FROM absences WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        overtimes = conn.execute(
            "SELECT date, hours, 'отработка' as type FROM overtimes WHERE user_id = ?",
            (user_id,)
        ).fetchall()
    all_records = [(r[0], r[1], r[2]) for r in absences + overtimes]
    return sorted(all_records, key=lambda r: r[0])


# ============================================================
# Экспорт в CSV (команда /отчёт)
# ============================================================

def export_user_csv(user_id: int) -> tuple:
    """
    Генерирует CSV-отчёт по пользователю.
    Возвращает (имя_файла, содержимое_в_байтах).
    """
    records = get_full_history(user_id)

    # Собираем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата", "Тип", "Часы"])

    for date, hours, rtype in records:
        writer.writerow([date, rtype, hours])

    # Итоговая строка
    balance = get_balance(user_id)
    if balance > 0:
        itog = f"Долг: {balance} ч"
    elif balance == 0:
        itog = "Долгов нет"
    else:
        itog = f"Переработка: {abs(balance)} ч"
    writer.writerow([])
    writer.writerow(["Итог", itog, ""])

    # BOM (Byte Order Mark) — чтобы Excel нормально открывал кириллицу
    csv_bytes = output.getvalue().encode('utf-8-sig')
    filename = f"otchet_{user_id}_{datetime.now().strftime('%Y-%m-%d')}.csv"

    return filename, csv_bytes


# ============================================================
# Логирование действий
# ============================================================

def log_to_db(user_id: int, action: str, target_user_id: int = None, details: str = ""):
    """
    Записывает действие в таблицу log.
    Возвращает строку для дублирования в консоль и/или канал логов.
    """
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO log (user_id, action, target_user_id, details) VALUES (?, ?, ?, ?)",
            (user_id, action, target_user_id, details)
        )
        conn.commit()

    return f"[LOG] user={user_id} action={action} target={target_user_id} details={details}"