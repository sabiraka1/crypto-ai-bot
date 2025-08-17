# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations
import sqlite3
import time
from typing import Optional, Tuple

class SqliteIdempotencyRepository:
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
                state TEXT NOT NULL DEFAULT 'claimed',
                created_ms INTEGER NOT NULL,
                committed INTEGER NOT NULL DEFAULT 0,
                updated_ms INTEGER NULL
            );
            """
        )
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_ms);")

    # ---- core API ----
    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000
        with self.con:
            row = self.con.execute("SELECT created_ms FROM idempotency WHERE key = ?", (key,)).fetchone()
            if row is None:
                self.con.execute(
                    "INSERT INTO idempotency(key, state, created_ms, committed) VALUES (?, 'claimed', ?, 0)",
                    (key, now_ms),
                )
                return True
            created = int(row[0])
            if created < threshold:
                self.con.execute(
                    "UPDATE idempotency SET state='claimed', created_ms=?, committed=0, updated_ms=NULL WHERE key=?",
                    (now_ms, key),
                )
                return True
            return False

    def commit(self, key: str, result: Optional[str] = None) -> None:
        now_ms = int(time.time() * 1000)
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET state='committed', committed=1, result=?, updated_ms=? WHERE key=?",
                (result, now_ms, key),
            )

    def release(self, key: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM idempotency WHERE key=?", (key,))

    def check_and_store(self, key: str, payload: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[str]]:
        """
        Возвращает (is_new, prev_result).
        Если новый — кладёт payload и возвращает (True, None).
        Если дубль — (False, result) если есть.
        """
        if self.claim(key, ttl_seconds=ttl_seconds):
            with self.con:
                self.con.execute(
                    "UPDATE idempotency SET payload=? WHERE key=?",
                    (payload, key),
                )
            return True, None

        # уже есть — возвращаем предыдущее result (если было commited)
        row = self.con.execute("SELECT result FROM idempotency WHERE key=?", (key,)).fetchone()
        prev = row[0] if row and row[0] is not None else None
        return False, prev

    def purge_expired(self, ttl_seconds: int = 3600) -> int:
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE created_ms < ?", (threshold,))
            return int(cur.rowcount or 0)

    # ---- alias for scheduler/API compatibility ----
    def cleanup_expired(self, ttl_seconds: int = 3600) -> int:
        return self.purge_expired(ttl_seconds=ttl_seconds)
