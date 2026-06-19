import sqlite3, sys
sys.path.insert(0, '.')
from config import DB_NAME

with sqlite3.connect(DB_NAME) as conn:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite%'"
        ).fetchall()
    ]
    print(f"tables: {tables}")
    for t in tables:
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        print(f"  {t}: {[c[1] for c in cols]}")
