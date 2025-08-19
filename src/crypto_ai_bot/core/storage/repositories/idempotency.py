from __future__ import annotations
import sqlite3
import time
from typing import Optional, Protocol

from crypto_ai_bot.utils.idempotency import validate_key


class IdempotencyRepository(Protocol):
    """Контракт для репозитория идемпотентности."""
    def check_and_store(self, key: str, ttl_seconds: int = 300) -> bool: ...
    def commit(self, key: str) -> None: ...
    def cleanup_expired(self, ttl_seconds: int = 300) -> int: ...
    # Для совместимости со старым кодом (если вызывали cleanup)
    def cleanup(self, ttl_seconds: int = 300) -> int: ...


class SqliteIdempotencyRepository:
    """
    Простой repo для идемпотентности (SQLite).
    Таблица:
      key TEXT PRIMARY KEY
      created_ms INTEGER NOT NULL
      committed INTEGER NOT NULL DEFAULT 0
      state TEXT
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency(
                key TEXT PRIMARY KEY,
                created_ms INTEGER NOT NULL,
                committed INTEGER NOT NULL DEFAULT 0,
                state TEXT
            );
            """
        )

    # ---- API ----

    def check_and_store(self, key: str, ttl_seconds: int = 300) -> bool:
        """
        Атомарно пытается «забронировать» ключ.
        Возвращает True, если бронь успешна (можно выполнять действие),
        False — если ключ уже существует и ещё «живой» (дубликат).
        Исключение ValueError — если ключ неверного формата.
        """
        if not validate_key(key):
            raise ValueError(f"invalid idempotency key: {key}")

        now = int(time.time() * 1000)
        ttl_ms = int(ttl_seconds) * 1000

        with self.con:
            row = self.con.execute(
                "SELECT created_ms, committed FROM idempotency WHERE key = ?",
                (key,),
            ).fetchone()

            if row:
                created_ms, committed = int(row[0]), int(row[1])
                if committed:
                    return False  # уже зафиксирован выполненный запрос
                # некоммитнутая запись: проверяем TTL
                if now - created_ms < ttl_ms:
                    return False  # ещё свежая => дубликат
                # просрочена: перезапишем
                self.con.execute(
                    "UPDATE idempotency SET created_ms=?, committed=0, state='claimed' WHERE key=?",
                    (now, key),
                )
                return True

            # нет записи — создаём бронь
            self.con.execute(
                "INSERT INTO idempotency(key, created_ms, committed, state) VALUES (?,?,0,'claimed')",
                (key, now),
            )
            return True

    def commit(self, key: str) -> None:
        """Помечает запись как завершённую (больше не дубликат)."""
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET committed=1, state='committed' WHERE key=?",
                (key,),
            )

    def cleanup_expired(self, ttl_seconds: int = 300) -> int:
        """
        Удаляет все НЕкоммитнутые записи старше TTL.
        Возвращает число удалённых строк.
        """
        now = int(time.time() * 1000)
        ttl_ms = int(ttl_seconds) * 1000
        with self.con:
            cur = self.con.execute(
                "DELETE FROM idempotency WHERE committed=0 AND (? - created_ms) > ?",
                (now, ttl_ms),
            )
            return int(cur.rowcount or 0)

    # Backward-compat: если где-то вызывали .cleanup(...)
    def cleanup(self, ttl_seconds: int = 300) -> int:
        return self.cleanup_expired(ttl_seconds)

    # (опционально) если где-то нужно посмотреть сырое состояние:
    def get(self, key: str) -> Optional[tuple]:
        return self.con.execute(
            "SELECT key, created_ms, committed, state FROM idempotency WHERE key=?",
            (key,),
        ).fetchone()


__all__ = ["IdempotencyRepository", "SqliteIdempotencyRepository"]
