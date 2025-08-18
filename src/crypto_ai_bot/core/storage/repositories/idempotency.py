# src/crypto_ai_bot/core/storage/repositories/idempotency.py
import time
import sqlite3
from typing import Optional

class SqliteIdempotencyRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS idempotency(
            key TEXT PRIMARY KEY,
            created_ms INTEGER NOT NULL,
            committed INTEGER NOT NULL DEFAULT 0,
            state TEXT
        );
        """)

    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        # атомарный захват через INSERT OR IGNORE, без SELECT→INSERT гонки
        now_ms = int(time.time() * 1000)
        with self.con:
            cur = self.con.execute(
                "INSERT OR IGNORE INTO idempotency(key, created_ms, committed, state) VALUES(?, ?, 0, 'claimed')",
                (key, now_ms)
            )
        if cur.rowcount == 1:
            return True
        # если запись есть и устарела — можно «перехватить»
        row = self.con.execute("SELECT created_ms, committed FROM idempotency WHERE key = ?", (key,)).fetchone()
        if not row:
            return False
        created_ms, committed = row
        if committed:
            return False
        if (now_ms - int(created_ms)) > ttl_seconds * 1000:
            with self.con:
                # безопасно обновляем состояние
                self.con.execute(
                    "UPDATE idempotency SET created_ms=?, state='reclaimed' WHERE key=? AND committed=0",
                    (now_ms, key)
                )
            return True
        return False

    def commit(self, key: str, state: Optional[str] = "committed") -> None:
        with self.con:
            self.con.execute("UPDATE idempotency SET committed=1, state=? WHERE key=?", (state, key))

    def release(self, key: str, state: Optional[str] = "released") -> None:
        with self.con:
            self.con.execute("UPDATE idempotency SET committed=0, state=? WHERE key=?", (state, key))

    def cleanup_expired(self, ttl_seconds: int = 300) -> int:
        th = int(time.time() * 1000) - ttl_seconds * 1000
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE committed=0 AND created_ms < ?", (th,))
            return cur.rowcount or 0
