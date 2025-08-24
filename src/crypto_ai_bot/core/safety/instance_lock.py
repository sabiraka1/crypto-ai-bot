from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ...utils.time import now_ms
from ...utils.logging import get_logger


@dataclass
class InstanceLock:
    """
    DB-based "single instance" лок. Не требует внешних сервисов.
    Создаёт служебную таблицу при первом использовании.
    """
    conn: "sqlite3.Connection"
    name: str = "trading-bot"

    def __post_init__(self) -> None:
        self._log = get_logger("safety.instance_lock")
        self._owner = f"{socket.gethostname()}:{os.getpid()}"
        self._ensure_table()

    # --- public API ---
    def acquire(self, ttl_sec: int = 300) -> bool:
        """Атомарная попытка захвата локa. Возвращает True/False."""
        now = now_ms()
        expires_at = now + int(Decimal(ttl_sec) * 1000)

        with self.conn:  # автотранзакция
            # 1) создать строку, если отсутствует или просрочена
            self.conn.execute(
                """
                INSERT INTO locks(name, owner, acquired_at_ms, expires_at_ms)
                SELECT ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM locks
                    WHERE name = ?
                      AND expires_at_ms > ?
                )
                """,
                (self.name, self._owner, now, expires_at, self.name, now),
            )
            # 2) проверить, наш ли лок
            row = self.conn.execute(
                "SELECT owner, expires_at_ms FROM locks WHERE name = ?",
                (self.name,),
            ).fetchone()

        if not row:
            return False

        owner, exp = row[0], int(row[1])
        if owner == self._owner:
            # мы владелец — обновим TTL
            with self.conn:
                self.conn.execute(
                    "UPDATE locks SET expires_at_ms = ? WHERE name = ? AND owner = ?",
                    (expires_at, self.name, self._owner),
                )
            self._log.info("lock_acquired", extra={"name": self.name, "owner": self._owner})
            return True

        # чужой валидный лок
        return False

    def heartbeat(self, ttl_sec: int = 300) -> None:
        """Обновить TTL, если мы владелец."""
        now = now_ms()
        expires_at = now + int(Decimal(ttl_sec) * 1000)
        with self.conn:
            self.conn.execute(
                """
                UPDATE locks
                SET expires_at_ms = ?
                WHERE name = ? AND owner = ?
                """,
                (expires_at, self.name, self._owner),
            )

    def release(self) -> None:
        """Освободить лок (если мы владелец)."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM locks WHERE name = ? AND owner = ?",
                (self.name, self._owner),
            )
        self._log.info("lock_released", extra={"name": self.name, "owner": self._owner})

    # --- helpers ---
    def _ensure_table(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS locks (
                    name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    acquired_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL
                )
                """
            )
