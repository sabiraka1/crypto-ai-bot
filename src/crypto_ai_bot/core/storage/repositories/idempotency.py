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
            state TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            payload_json TEXT
        )
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self._ensure_schema()

    # --- schema ---------------------------------------------------------
    def _ensure_schema(self) -> None:
        # Проверяем, существует ли таблица
        cursor = self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='idempotency'"
        )
        if cursor.fetchone() is None:
            # Создаём новую таблицу с правильной схемой
            self.con.execute(
                """
                CREATE TABLE idempotency (
                    key TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'claimed',
                    expires_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    payload_json TEXT,
                    created_ms INTEGER,
                    committed INTEGER DEFAULT 0,
                    result TEXT
                )
                """
            )
            self.con.execute(
                "CREATE INDEX IF NOT EXISTS idx_idem_expires ON idempotency(expires_at)"
            )

    # --- core ops -------------------------------------------------------
    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        """
        Захват ключа:
          - если записи нет -> вставка -> True
          - если запись есть и истек TTL -> заменить expires_at -> True
          - иначе -> False
        """
        now_ms = int(time.time() * 1000)
        expires_at = now_ms + ttl_seconds * 1000

        with self.con:
            # Проверяем существующую запись
            row = self.con.execute(
                "SELECT expires_at FROM idempotency WHERE key = ?", 
                (key,)
            ).fetchone()
            
            if row is None:
                # Новая запись
                self.con.execute(
                    """INSERT INTO idempotency(key, state, expires_at, updated_at, created_ms, committed) 
                       VALUES (?, 'claimed', ?, ?, ?, 0)""",
                    (key, expires_at, now_ms, now_ms),
                )
                return True

            existing_expires = int(row[0])
            if existing_expires < now_ms:
                # Просрочено — перехватываем
                self.con.execute(
                    """UPDATE idempotency 
                       SET expires_at = ?, updated_at = ?, state = 'claimed', committed = 0 
                       WHERE key = ?""",
                    (expires_at, now_ms, key),
                )
                return True

            return False

    def commit(self, key: str, payload_json: Optional[str] = None) -> bool:
        """Коммит операции с опциональным сохранением результата"""
        now_ms = int(time.time() * 1000)
        with self.con:
            if payload_json:
                cur = self.con.execute(
                    """UPDATE idempotency 
                       SET committed = 1, state = 'committed', payload_json = ?, updated_at = ? 
                       WHERE key = ?""",
                    (payload_json, now_ms, key),
                )
            else:
                cur = self.con.execute(
                    """UPDATE idempotency 
                       SET committed = 1, state = 'committed', updated_at = ? 
                       WHERE key = ?""",
                    (now_ms, key),
                )
            return cur.rowcount > 0

    def release(self, key: str) -> bool:
        """Освобождение ключа (удаление)"""
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE key = ?", (key,))
            return cur.rowcount > 0

    def purge_expired(self, ttl_seconds: int = 300) -> int:
        """Удаление просроченных записей"""
        now_ms = int(time.time() * 1000)
        with self.con:
            cur = self.con.execute(
                "DELETE FROM idempotency WHERE expires_at < ?", 
                (now_ms,)
            )
            return cur.rowcount

    def check_and_store(self, key: str, payload: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[str]]:
        """
        Возвращает (is_new, previous_payload).
          - Если удалось захватить — сохраняем payload и возвращаем (True, None).
          - Если захват не удался — возвращаем (False, предыдущий payload).
        """
        if self.claim(key, ttl_seconds=ttl_seconds):
            now_ms = int(time.time() * 1000)
            with self.con:
                self.con.execute(
                    "UPDATE idempotency SET payload_json = ?, updated_at = ? WHERE key = ?",
                    (payload, now_ms, key),
                )
            return True, None

        row = self.con.execute("SELECT payload_json FROM idempotency WHERE key = ?", (key,)).fetchone()
        prev = row[0] if row else None
        return False, prev

    def get_original(self, key: str) -> Optional[str]:
        """Получение оригинального payload"""
        row = self.con.execute("SELECT payload_json FROM idempotency WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    
    def get_original_order(self, key: str) -> Optional[str]:
        """Алиас для совместимости с тестами"""
        return self.get_original(key)