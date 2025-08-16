# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations

import sqlite3
import time
from typing import Optional

class IdempotencyRepositorySQLite:
    """
    Простая таблица ключей идемпотентности:
      - record(key, ttl_seconds) → True, если новый; False, если ещё живой.
      - purge_expired() → удаляет протухшие.
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con

    def record(self, key: str, ttl_seconds: int) -> bool:
        now = int(time.time() * 1000)
        expires = now + int(ttl_seconds * 1000)
        try:
            self.con.execute(
                "INSERT INTO idempotency_keys(key, created_at, expires_at) VALUES(?,?,?);",
                (key, now, expires),
            )
            return True
        except sqlite3.IntegrityError:
            # уже существует — проверим не протух ли
            cur = self.con.execute("SELECT expires_at FROM idempotency_keys WHERE key=?;", (key,))
            row = cur.fetchone()
            if not row:
                return False
            if int(row[0]) < now:
                # протух — перезапишем
                self.con.execute(
                    "UPDATE idempotency_keys SET created_at=?, expires_at=? WHERE key=?;",
                    (now, expires, key),
                )
                return True
            return False

    def purge_expired(self) -> int:
        now = int(time.time() * 1000)
        cur = self.con.execute("DELETE FROM idempotency_keys WHERE expires_at < ?;", (now,))
        return int(cur.rowcount or 0)
