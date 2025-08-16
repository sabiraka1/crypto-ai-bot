
from __future__ import annotations

import sqlite3
import time
from typing import Optional, Tuple

class SqliteIdempotencyRepository:
    """
    Минимальный и предсказуемый репозиторий идемпотентности под unit-тесты.

    Схема (создаётся лениво):
        idempotency(
            key TEXT PRIMARY KEY,
            payload TEXT NULL,
            result TEXT NULL,
            created_ms INTEGER NOT NULL,
            committed INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'claimed',
            updated_ms INTEGER NULL
        )
    Индексы: created_ms для TTL.
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self._ensure_schema()

    # --- schema ---------------------------------------------------------
    def _ensure_schema(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                payload TEXT NULL,
                result TEXT NULL,
                created_ms INTEGER NOT NULL,
                committed INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'claimed',
                updated_ms INTEGER NULL
            );
            """
        )
        # добавим недостающие колонки для старых БД
        cols = {row[1] for row in self.con.execute("PRAGMA table_info(idempotency)").fetchall()}
        if "state" not in cols:
            self.con.execute("ALTER TABLE idempotency ADD COLUMN state TEXT NOT NULL DEFAULT 'claimed'")
        if "updated_ms" not in cols:
            self.con.execute("ALTER TABLE idempotency ADD COLUMN updated_ms INTEGER NULL")
        if "payload" not in cols:
            self.con.execute("ALTER TABLE idempotency ADD COLUMN payload TEXT NULL")
        if "result" not in cols:
            self.con.execute("ALTER TABLE idempotency ADD COLUMN result TEXT NULL")
        if "committed" not in cols:
            self.con.execute("ALTER TABLE idempotency ADD COLUMN committed INTEGER NOT NULL DEFAULT 0")
        if "created_ms" not in cols:
            self.con.execute("ALTER TABLE idempotency ADD COLUMN created_ms INTEGER NOT NULL DEFAULT 0")

        self.con.execute(
            "CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_ms)"
        )

    # --- core ops -------------------------------------------------------
    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        """
        Захват ключа:
          - если записи нет -> вставка -> True
          - если запись есть и истек TTL -> заменить created_ms -> True
          - иначе -> False
        """
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

            created_ms = int(row[0])
            if created_ms < threshold:
                # просрочено — перехватываем
                self.con.execute(
                    "UPDATE idempotency SET created_ms = ?, committed = 0, state = 'claimed', updated_ms = ? WHERE key = ?",
                    (now_ms, now_ms, key),
                )
                return True

            return False

    def commit(self, key: str, result: Optional[str] = None) -> bool:
        now_ms = int(time.time() * 1000)
        with self.con:
            cur = self.con.execute(
                "UPDATE idempotency SET committed = 1, state = 'committed', result = COALESCE(?, result), updated_ms = ? WHERE key = ?",
                (result, now_ms, key),
            )
            return cur.rowcount > 0

    def release(self, key: str) -> bool:
        # Для простоты — удаляем ключ
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE key = ?", (key,))
            return cur.rowcount > 0

    def purge_expired(self, ttl_seconds: int) -> int:
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE created_ms < ?", (threshold,))
            return cur.rowcount

    def check_and_store(self, key: str, payload: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[str]]:
        """
        Возвращает (is_new, previous_payload).
          - Если удалось захватить — сохраняем payload и возвращаем (True, None).
          - Если захват не удался — возвращаем (False, предыдущее payload).
        """
        if self.claim(key, ttl_seconds=ttl_seconds):
            now_ms = int(time.time() * 1000)
            with self.con:
                self.con.execute(
                    "UPDATE idempotency SET payload = ?, updated_ms = ? WHERE key = ?",
                    (payload, now_ms, key),
                )
            return True, None

        row = self.con.execute("SELECT payload FROM idempotency WHERE key = ?", (key,)).fetchone()
        prev = row[0] if row else None
        return False, prev

    def get_original(self, key: str) -> Optional[str]:
        row = self.con.execute("SELECT payload FROM idempotency WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
