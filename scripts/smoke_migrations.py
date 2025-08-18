# scripts/smoke_migrations.py
import os
import sqlite3
from crypto_ai_bot.core.storage.migrations.runner import apply_all

DB = "file:smoke_migrations.sqlite?mode=rwc"

def main():
    # старт с нуля
    if os.path.exists("smoke_migrations.sqlite"):
        os.remove("smoke_migrations.sqlite")
    con = sqlite3.connect("smoke_migrations.sqlite", isolation_level=None, check_same_thread=False, timeout=5.0)
    apply_all(con)

    # повторное применение (идемпотентность)
    apply_all(con)

    # sanity-check — проверим несколько колонок
    cols = {r[1] for r in con.execute("PRAGMA table_info(trades);").fetchall()}
    needed = {"order_id", "state", "fee_amt", "fee_ccy"}
    missing = needed - cols
    assert not missing, f"missing columns in trades: {missing}"

    print("OK: migrations applied idempotently")

if __name__ == "__main__":
    main()
