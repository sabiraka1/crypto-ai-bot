import sqlite3
import pytest
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.utils.time import now_ms

def test_migrations_run(temp_db):
    conn, db_path = temp_db
    version = run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=False)
    
    assert version is not None
    
    # Проверяем основные таблицы
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    
    assert "positions" in tables
    assert "trades" in tables
    assert "idempotency" in tables or "idempotency_keys" in tables
    assert "schema_migrations" in tables