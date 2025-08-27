from __future__ import annotations

import sqlite3
from typing import Optional
from ....utils.time import now_ms

class IdempotencyRepository:
    """
    Выравнено под схему из миграций:
      idempotency_keys(id INTEGER PK,
                       bucket_ms INTEGER NOT NULL,
                       key TEXT NOT NULL,
                       created_at_ms INTEGER NOT NULL,
                       expires_at_ms INTEGER NOT NULL)
    + уникальный индекс по key (см. V0005__schema_fixes.sql)

    Семантика:
      - удаляем протухшие записи по expires_at_ms
      - пытаемся вставить новую; при конфликте key → считаем дубликатом
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def check_and_store(self, *, key: str, ttl_sec: int, default_bucket_ms: int = 60000) -> bool:
        """
        Вернёт True, если ключ свежесохранён (не было активной записи).
        Вернёт False, если такой ключ уже существует и ещё не истёк.
        """
        now = now_ms()
        # 1) очистка протухших
        self._c.execute("DELETE FROM idempotency_keys WHERE expires_at_ms < ?", (now,))

        expires = now + int(ttl_sec) * 1000
        try:
            # 2) попытка вставки (уникальность обеспечивается индексом на key)
            self._c.execute(
                """
                INSERT INTO idempotency_keys(bucket_ms, key, created_at_ms, expires_at_ms)
                VALUES (?, ?, ?, ?)
                """,
                (int(default_bucket_ms), key, now, expires),
            )
            return True
        except sqlite3.IntegrityError:
            # уже есть активная запись с таким key
            return False

    def prune_older_than(self, seconds: int = 604800) -> int:
        cutoff = now_ms() - int(seconds) * 1000
        cur = self._c.execute("DELETE FROM idempotency_keys WHERE expires_at_ms < ?", (cutoff,))
        return cur.rowcount or 0
