# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations

import sqlite3
import time
from typing import Optional


def _now_ms() -> int:
    return int(time.time() * 1000)


class IdempotencyRepositorySQLite:
    """
    Простая идемпотентность:
      record(key, ttl) -> True, если ключ "свежий" и зафиксирован впервые/после истечения
                        -> False, если для ключа ещё не истёк TTL (дубликат)
      purge_expired()  -> число удалённых записей

    Таблица (см. миграцию 0003_idempotency.sql):
      idempotency (key TEXT PRIMARY KEY, created_at_ms INTEGER, ttl_seconds INTEGER, expires_at_ms INTEGER)
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def record(self, key: str, ttl_seconds: int) -> bool:
        now = _now_ms()
        cur = self.con.cursor()

        # 1) быстрый просмотр текущего состояния
        cur.execute("SELECT expires_at_ms FROM idempotency WHERE key = ?", (key,))
        row = cur.fetchone()
        if row:
            expires_at = int(row[0])
            if expires_at > now:
                # ключ ещё "жив" → это повтор
                return False

        # 2) либо ключа не было, либо он истёк → записываем/обновляем
        expires_at_ms = now + ttl_seconds * 1000
        cur.execute(
            """
            INSERT INTO idempotency(key, created_at_ms, ttl_seconds, expires_at_ms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                created_at_ms=excluded.created_at_ms,
                ttl_seconds=excluded.ttl_seconds,
                expires_at_ms=excluded.expires_at_ms
            """,
            (key, now, int(ttl_seconds), int(expires_at_ms)),
        )
        self.con.commit()
        return True

    def purge_expired(self) -> int:
        now = _now_ms()
        cur = self.con.cursor()
        cur.execute("DELETE FROM idempotency WHERE expires_at_ms < ?", (now,))
        deleted = cur.rowcount or 0
        self.con.commit()
        return int(deleted)
