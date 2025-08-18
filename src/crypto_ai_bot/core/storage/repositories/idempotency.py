from __future__ import annotations
import sqlite3, time
from typing import Optional

DDL = """
CREATE TABLE IF NOT EXISTS idempotency(
  key TEXT PRIMARY KEY,
  created_ms INTEGER NOT NULL,
  committed INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'claimed'
);
"""
IDX = "CREATE UNIQUE INDEX IF NOT EXISTS idx_idem_key ON idempotency(key);"

class IdempotencyRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute(DDL)
        self.con.execute(IDX)

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def cleanup_expired(self, ttl_seconds: int = 300) -> int:
        """Удаляет старые ключи, у которых TTL вышел (и не зафиксированы)."""
        now = self._now_ms()
        limit_ms = now - int(ttl_seconds) * 1000
        with self.con:
            cur = self.con.execute(
                "DELETE FROM idempotency WHERE committed=0 AND created_ms < ?", (limit_ms,)
            )
        return cur.rowcount

    # --- основной атомарный метод ---

    def check_and_store(self, key: str, ttl_seconds: int = 300) -> bool:
        """
        Атомарная попытка «захватить» ключ.
        True  -> мы первые (можно выполнять действие)
        False -> ключ уже есть/просрочен (дубликат или устаревший)
        """
        now = self._now_ms()
        # 1) пробуем вставить (если ключ уже есть – вставка проигнорируется)
        with self.con:
            self.con.execute(
                "INSERT OR IGNORE INTO idempotency(key, created_ms, committed, state) VALUES (?,?,0,'claimed')",
                (key, now),
            )
        # 2) проверяем текущее состояние ключа
        row = self.con.execute("SELECT created_ms, committed FROM idempotency WHERE key=?", (key,)).fetchone()
        if row is None:
            return False
        created_ms, committed = int(row[0]), int(row[1])
        if committed:
            return False
        # TTL ещё не вышел => наш захват валиден
        if (now - created_ms) <= int(ttl_seconds) * 1000:
            return True
        # просрочено – трактуем как нельзя выполнять
        return False

    def commit(self, key: str) -> None:
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET committed=1, state='committed' WHERE key=?", (key,)
            )
