# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations

import sqlite3
import time
from typing import Optional, Tuple

class SqliteIdempotencyRepository:
    """
    Простой репозиторий идемпотентности:
      key (PK), payload, result, created_ms, committed, updated_ms
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                payload TEXT NULL,
                result TEXT NULL,
                created_ms INTEGER NOT NULL,
                committed INTEGER NOT NULL DEFAULT 0,
                updated_ms INTEGER NULL
            );
            """
        )
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_ms);")

    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000
        with self.con:
            row = self.con.execute("SELECT created_ms FROM idempotency WHERE key = ?", (key,)).fetchone()
            if row is None:
                self.con.execute(
                    "INSERT INTO idempotency(key, created_ms, committed) VALUES (?, ?, 0)",
                    (key, now_ms),
                )
                return True
            # запись есть — если истекла, перезахватываем
            created_ms = int(row[0])
            if created_ms < threshold:
                self.con.execute(
                    "UPDATE idempotency SET created_ms = ?, committed = 0, result = NULL, updated_ms = NULL WHERE key = ?",
                    (now_ms, key),
                )
                return True
        return False

    def check_and_store(self, key: str, payload: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[str]]:
        """
        True/None — новый ключ записан,
        False/prev_result — дубликат/актуальная запись.
        """
        if self.claim(key, ttl_seconds=ttl_seconds):
            with self.con:
                self.con.execute(
                    "UPDATE idempotency SET payload = ?, updated_ms = ? WHERE key = ?",
                    (payload, int(time.time() * 1000), key),
                )
            return True, None
        # дубликат
        row = self.con.execute("SELECT result FROM idempotency WHERE key = ?", (key,)).fetchone()
        return False, (row[0] if row and row[0] is not None else None)

    def commit(self, key: str, result: str) -> None:
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET committed = 1, result = ?, updated_ms = ? WHERE key = ?",
                (result, int(time.time() * 1000), key),
            )

    def release(self, key: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM idempotency WHERE key = ?", (key,))

    def purge_expired(self, ttl_seconds: int = 300) -> int:
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE committed = 0 AND created_ms < ?", (threshold,))
        return cur.rowcount if hasattr(cur, "rowcount") else 0

    # alias required by dashboards/spec
    def cleanup_expired(self, ttl_seconds: int = 300) -> int:
        return self.purge_expired(ttl_seconds=ttl_seconds)
