# tests/unit/test_idempotency.py
from __future__ import annotations
import sqlite3
import time

import pytest

from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository


def _mk_con() -> sqlite3.Connection:
    """Создаём соединение и позволяем репозиторию самому создать схему"""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def test_claim_commit_release_cycle():
    con = _mk_con()
    repo = SqliteIdempotencyRepository(con)

    key = "BTC/USDT:buy:0.01:123456:deadbeef"
    assert repo.claim(key, ttl_seconds=1) is True         # первый захват
    assert repo.claim(key, ttl_seconds=1) is False        # повторный захват — нельзя

    # commit с payload
    repo.commit(key, payload_json='{"order":{"id":"1"}}')
    assert repo.get_original_order(key) is not None

    # release очищает запись
    repo.release(key)
    assert repo.get_original_order(key) is None


def test_check_and_store_and_duplicate():
    con = _mk_con()
    repo = SqliteIdempotencyRepository(con)

    key = "ETH/USDT:buy:0.02:123456:beadfeed"
    is_new, prev = repo.check_and_store(key, '{"decision":{}}', ttl_seconds=1)
    assert is_new is True and prev is None

    # повтор за TTL — дубликат
    is_new, prev = repo.check_and_store(key, '{"decision":{}}', ttl_seconds=1)
    assert is_new is False
    assert prev == '{"decision":{}}'  # теперь должен вернуть сохранённый payload

    # после commit — get_original_order() должен вернуть финальный payload
    repo.commit(key, payload_json='{"order":{"id":"77"}}')
    got = repo.get_original_order(key)
    assert got is not None and '"77"' in got


def test_purge_expired():
    con = _mk_con()
    repo = SqliteIdempotencyRepository(con)

    # Создаём запись с очень коротким TTL
    assert repo.claim("K:1", ttl_seconds=0) is True
    
    # Ждём немного
    time.sleep(0.01)
    
    # Удаляем просроченные записи
    purged = repo.purge_expired()
    assert purged >= 1
    
    # Проверяем, что запись удалена
    assert repo.get_original("K:1") is None


def test_ttl_expiration_allows_reclaim():
    """Тест на то, что после истечения TTL можно снова захватить ключ"""
    con = _mk_con()
    repo = SqliteIdempotencyRepository(con)
    
    key = "TEMP:key"
    
    # Первый захват с очень коротким TTL
    assert repo.claim(key, ttl_seconds=0) is True
    
    # Немедленная попытка захвата должна провалиться, если TTL=0 означает "истекает сразу"
    # но наша реализация проверяет expires_at > now_ms, так что при TTL=0 он сразу истекает
    time.sleep(0.001)  # минимальная задержка
    
    # Теперь должны мочь захватить снова
    assert repo.claim(key, ttl_seconds=1) is True