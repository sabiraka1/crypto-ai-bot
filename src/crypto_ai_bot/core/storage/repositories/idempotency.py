# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations
import sqlite3
import time
from typing import Optional, Tuple

class SqliteIdempotencyRepository:
    """
    Уже проходят unit-тесты claim/commit/release/check_and_store.
    Добавляем совместимый alias cleanup_expired() → purge_expired() для планового обслуживания.
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
                updated_ms INTEGER NULL,
                state TEXT NOT NULL DEFAULT 'claimed'
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
                    "INSERT INTO idempotency(key, created_ms, committed, state) VALUES (?, ?, 0, 'claimed')",
                    (key, now_ms),
                )
                return True
            created_ms, = row
            if created_ms < threshold:
                # истекло — перехватываем ключ
                self.con.execute(
                    "UPDATE idempotency SET created_ms=?, committed=0, state='claimed', updated_ms=NULL, payload=NULL, result=NULL WHERE key=?",
                    (now_ms, key),
                )
                return True
            return False

    def commit(self, key: str, result_json: Optional[str] = None) -> None:
        now_ms = int(time.time() * 1000)
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET committed=1, result=?, state='committed', updated_ms=? WHERE key=?",
                (result_json, now_ms, key),
            )

    def release(self, key: str) -> None:
        # снимаем захват (например, при ошибке) — просто удаляем ключ
        with self.con:
            self.con.execute("DELETE FROM idempotency WHERE key=?", (key,))

    def check_and_store(self, key: str, payload_json: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[str]]:
        """
        Возвращает (is_new, prev_result).
        """
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000

        with self.con:
            row = self.con.execute("SELECT committed, result, created_ms FROM idempotency WHERE key=?", (key,)).fetchone()
            if row is None:
                # нет записи — создаём
                self.con.execute(
                    "INSERT INTO idempotency(key, payload, created_ms, committed, state) VALUES (?, ?, ?, 0, 'claimed')",
                    (key, payload_json, now_ms),
                )
                return True, None

            committed, result, created_ms = row
            if created_ms < threshold:
                # просрочено — обновляем
                self.con.execute(
                    "UPDATE idempotency SET payload=?, created_ms=?, committed=0, state='claimed', updated_ms=NULL, result=NULL WHERE key=?",
                    (payload_json, now_ms, key),
                )
                return True, None

            # актуальная запись
            return False, result

    def purge_expired(self, older_than_ms: int) -> int:
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE created_ms < ?", (older_than_ms,))
            return cur.rowcount

    # === новый alias под планировщик ===
    def cleanup_expired(self, ttl_seconds: int = 300) -> int:
        now_ms = int(time.time() * 1000)
        return self.purge_expired(now_ms - ttl_seconds * 1000)
