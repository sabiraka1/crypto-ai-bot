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
        # зачистка просроченных ключей (best-effort)
        try:
            self._c.execute("DELETE FROM idempotency_keys WHERE created_at_ms < ?", (now - ttl_sec * 1000,))
        except Exception:
            pass
        try:
            self._c.execute("INSERT INTO idempotency_keys(key, created_at_ms) VALUES (?, ?)", (key, now))
            return True
        except sqlite3.IntegrityError:
            return False

    def cleanup(self, *, before_ms: int) -> int:
        """Удалить ключи, созданные до before_ms (UTC, ms). Возвращает кол-во удалённых записей."""
        cur = self._c.execute("DELETE FROM idempotency_keys WHERE created_at_ms < ?", (before_ms,))
        return cur.rowcount or 0

    # ✅ новый метод для оркестратора: безопасный ретеншн по "возрасту" в секундах
    def prune_older_than(self, age_sec: int) -> int:
        """Удалить ключи старше age_sec секунд от текущего времени. Возвращает кол-во удалённых записей."""
        if age_sec <= 0:
            return 0
        cutoff = now_ms() - int(age_sec) * 1000
        cur = self._c.execute("DELETE FROM idempotency_keys WHERE created_at_ms < ?", (cutoff,))
        return cur.rowcount or 0

    def prune_older_than_ttl(self, ttl_sec: int) -> int:
        """
        Удаляет ключи старше now - ttl_sec.
        Возвращает число удалённых строк.
        """
        cutoff_ms = now_ms() - int(ttl_sec) * 1000
        cur = self._c.cursor()
        cur.execute("DELETE FROM idempotency_keys WHERE created_at_ms < ?", (cutoff_ms,))
        n = cur.rowcount or 0
        self._c.commit()
        return n