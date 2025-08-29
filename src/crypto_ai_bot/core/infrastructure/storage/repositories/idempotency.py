from __future__ import annotations

import sqlite3
from typing import Optional

from crypto_ai_bot.utils.time import now_ms


class IdempotencyRepository:
    """
    Таблица:

      idempotency(
        bucket_ms      INTEGER NOT NULL,
        key            TEXT    NOT NULL,
        created_at_ms  INTEGER NOT NULL,
        PRIMARY KEY(bucket_ms, key)
      )

    TTL не храним — чистим по created_at_ms.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                bucket_ms INTEGER NOT NULL,
                key TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL,
                PRIMARY KEY(bucket_ms, key)
            )
            """
        )
        self._conn.commit()

    def check_and_store(self, key: str, ttl_sec: int, default_bucket_ms: int = 60_000) -> bool:
        """
        True  -> ключ записан впервые в текущем time-bucket (не дубликат)
        False -> запись уже была (дубликат)
        """
        cur = self._conn.cursor()
        now = now_ms()

        # 1) очистка протухших ключей (безопасно глобально)
        cur.execute(
            "DELETE FROM idempotency WHERE (? - created_at_ms) > (? * 1000)",
            (now, int(ttl_sec)),
        )

        # 2) нормальный расчёт bucket для текущего момента
        bucket = (now // int(default_bucket_ms)) * int(default_bucket_ms)

        # 3) вставка с использованием ВЫЧИСЛЕННОГО bucket (раньше тут была ошибка)
        cur.execute(
            """
            INSERT OR IGNORE INTO idempotency(bucket_ms, key, created_at_ms)
            VALUES (?, ?, ?)
            """,
            (int(bucket), key, now),
        )
        self._conn.commit()

        # rowcount==0 => конфликт PK => дубликат
        return bool(cur.rowcount)

    def next_client_order_id(self, exchange: str, tag: str, *, bucket_ms: int) -> str:
        bucket = (now_ms() // int(bucket_ms)) * int(bucket_ms)
        return f"{exchange}-{tag}-{bucket}"

    def prune_older_than(self, seconds: int = 7 * 24 * 3600) -> int:
        cutoff = now_ms() - int(seconds) * 1000
        cur = self._conn.execute(
            "DELETE FROM idempotency WHERE created_at_ms < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cur.rowcount or 0

    def clear_all(self) -> None:
        self._conn.execute("DELETE FROM idempotency")
        self._conn.commit()


# Совместимость со старым именем
IdempotencyRepo = IdempotencyRepository
