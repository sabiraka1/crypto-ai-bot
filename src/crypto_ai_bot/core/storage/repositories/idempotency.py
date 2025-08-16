# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations
import sqlite3
import time
from typing import Optional

from crypto_ai_bot.core.storage.interfaces import IdempotencyRepository


class SqliteIdempotencyRepository(IdempotencyRepository):  # type: ignore[misc]
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def claim(self, key: str, ttl_seconds: int) -> bool:
        now = self._now_ms()
        exp = now + int(ttl_seconds * 1000)
        # если ключ не существует или истёк — «захватываем»
        cur = self._con.execute("SELECT state, expires_at FROM idempotency WHERE key = ?;", (key,))
        row = cur.fetchone()
        if row is None or int(row["expires_at"]) <= now:
            self._con.execute(
                """
                INSERT INTO idempotency(key, state, expires_at, updated_at)
                VALUES(?, 'claimed', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    state='claimed', expires_at=excluded.expires_at, updated_at=excluded.updated_at
                """,
                (key, exp, now),
            )
            return True
        # уже существует и ещё не истёк
        return False

    def commit(self, key: str) -> None:
        now = self._now_ms()
        # переводим в committed и продлеваем, чтобы защищать от повтора
        self._con.execute(
            "UPDATE idempotency SET state='committed', expires_at=?, updated_at=? WHERE key=?;",
            (now + 24 * 3600 * 1000, now, key),
        )

    def release(self, key: str) -> None:
        # удаляем ключ (или можно сбрасывать в claimed/expired — на твой выбор)
        self._con.execute("DELETE FROM idempotency WHERE key = ?;", (key,))
