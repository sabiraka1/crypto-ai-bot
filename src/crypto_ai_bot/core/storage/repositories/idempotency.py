## `core/storage/repositories/idempotency.py`
from __future__ import annotations
import sqlite3
from typing import Optional
from ....utils.time import now_ms
class IdempotencyRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
    def check_and_store(self, key: str, *, ttl_sec: int) -> bool:
        """Атомарно сохранить ключ идемпотентности.
        Возвращает True, если ключ сохранён впервые; False, если уже существовал.
        """
        if not key:
            raise ValueError("key must be non-empty")
        now = now_ms()
        try:
            self._c.execute("DELETE FROM idempotency_keys WHERE created_at_ms < ?", (now - ttl_sec * 1000,))
        except Exception:
            pass
        try:
            cur = self._c.execute("INSERT INTO idempotency_keys(key, created_at_ms) VALUES (?, ?)", (key, now))
            return True
        except sqlite3.IntegrityError:
            return False
    def cleanup(self, *, before_ms: int) -> int:
        cur = self._c.execute("DELETE FROM idempotency_keys WHERE created_at_ms < ?", (before_ms,))
        return cur.rowcount or 0