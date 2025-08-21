from __future__ import annotations
import sqlite3, time
from crypto_ai_bot.core.storage.repositories import ensure_schema


class IdempotencyRepositoryImpl:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        ensure_schema(self.conn)

    def check_and_store(self, key: str, ttl: int) -> bool:
        """Если ключ ещё не существует или истёк — сохраняем и возвращаем True; иначе False."""
        now_ms = int(time.time() * 1000)
        cur = self.conn.cursor()
        cur.execute("DELETE FROM idempotency_keys WHERE expires_at_ms < ?", (now_ms,))
        self.conn.execute("""
            INSERT OR IGNORE INTO idempotency_keys(key, expires_at_ms)
            VALUES (?, ?)
        """, (key, now_ms + int(ttl) * 1000))
        self.conn.commit()
        cur.execute("SELECT 1 FROM idempotency_keys WHERE key=?", (key,))
        ok = cur.fetchone() is not None
        cur.close()
        return ok

    def commit(self, key: str) -> None:
        # В простой реализации просто оставляем ключ до истечения TTL (чтобы повтор не сработал)
        return None

    def cleanup_expired(self) -> int:
        now_ms = int(time.time() * 1000)
        cur = self.conn.cursor()
        cur.execute("DELETE FROM idempotency_keys WHERE expires_at_ms < ?", (now_ms,))
        n = cur.rowcount if cur.rowcount is not None else 0
        cur.close()
        self.conn.commit()
        return int(n)
