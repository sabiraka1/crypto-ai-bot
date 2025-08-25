from __future__ import annotations

import sqlite3


class IdempotencyRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                expire_at INTEGER NOT NULL
            )
            """
        )

    def check_and_store(self, *, key: str, ttl_sec: int) -> bool:
        """Вернёт True, если ключ не существовал/просрочен и теперь сохранён."""
        self._c.execute(
            "DELETE FROM idempotency_keys WHERE expire_at < strftime('%s','now')"
        )
        cur = self._c.execute(
            """
            INSERT INTO idempotency_keys(key, expire_at)
            VALUES(?, strftime('%s','now') + ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, int(ttl_sec)),
        )
        # sqlite не возвращает affected rows на DO NOTHING; перепроверим
        cur = self._c.execute("SELECT 1 FROM idempotency_keys WHERE key=?", (key,))
        return bool(cur.fetchone())

    def prune_older_than(self, seconds: int = 604800) -> int:
        cur = self._c.execute(
            "DELETE FROM idempotency_keys WHERE expire_at < strftime('%s','now') - ?",
            (int(seconds),),
        )
        return cur.rowcount or 0