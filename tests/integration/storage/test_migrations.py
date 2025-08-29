import sqlite3
import pytest
from crypto_ai_bot.core.infrastructure.storage.migrations.runner import run_migrations
from crypto_ai_bot.utils.time import now_ms

def test_migrations_run(temp_db):
    """Тест выполнения миграций."""
    conn, db_path = temp_db
    
    # Запускаем миграции
    version = run_migrations(
        conn, 
        now_ms=now_ms(), 
        db_path=db_path, 
        do_backup=False
    )
    
    assert version is not None
    assert "baseline" in version.lower()
    
    # Проверяем основные таблицы
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    
    # Обязательные таблицы
    assert "positions" in tables
    assert "trades" in tables
    assert "schema_migrations" in tables
    
    # Одна из двух таблиц идемпотентности должна быть
    assert "idempotency" in tables or "idempotency_keys" in tables
    
    # Проверяем структуру positions
    cur = conn.execute("PRAGMA table_info(positions)")
    columns = {row[1] for row in cur.fetchall()}
    assert "symbol" in columns
    assert "base_qty" in columns
    
    # Проверяем структуру trades
    cur = conn.execute("PRAGMA table_info(trades)")
    columns = {row[1] for row in cur.fetchall()}
    assert "symbol" in columns
    assert "side" in columns
    assert "amount" in columns

def test_migrations_idempotent(temp_db):
    """Тест что миграции идемпотентны."""
    conn, db_path = temp_db
    
    # Первый запуск
    version1 = run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=False)
    
    # Второй запуск
    version2 = run_migrations(conn, now_ms=now_ms(), db_path=db_path, do_backup=False)
    
    assert version1 == version2
    
    # Проверяем что не дублировались записи
    cur = conn.execute("SELECT COUNT(*) FROM schema_migrations")
    count = cur.fetchone()[0]
    assert count == 1  # Только одна запись о миграции