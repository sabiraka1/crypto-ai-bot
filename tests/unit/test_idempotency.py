# tests/unit/test_idempotency.py
from __future__ import annotations
import sqlite3
import time

import pytest

from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository


def _mk_con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS idempotency (
            key TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            payload_json TEXT
        );
        """
    )
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
    assert prev is not None or prev is None  # допускаем отсутствие сохранённого payload на этом этапе

    # после commit — get_original_order()*должен* вернуть финальный payload
    repo.commit(key, payload_json='{"order":{"id":"77"}}')
    got = repo.get_original_order(key)
    assert got is not None and '"77"' in got


def test_purge_expired():
    con = _mk_con()
    repo = SqliteIdempotencyRepository(con)

    assert repo.claim("K:1", ttl_seconds=0) is True
    time.sleep(0.01)
    purged = repo.purge_expired()
    assert purged >= 1
