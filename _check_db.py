import sqlite3
from db.schema import init_db

# Вызываем init_db() — она использует config.DB_NAME = "worktime.db"
init_db()

# Проверяем worktime.db
conn = sqlite3.connect("worktime.db")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Таблицы в worktime.db:", sorted(tables))
print("duty_admin есть:", "duty_admin" in tables)
conn.close()