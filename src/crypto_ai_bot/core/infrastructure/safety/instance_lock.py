from __future__ import annotations

import time
import sqlite3
from dataclasses import dataclass

from ...utils.logging import get_logger

_log = get_logger("safety.lock")


@dataclass
class InstanceLock:
    conn: sqlite3.Connection
    app: str
    owner: str

    def acquire(self, ttl_sec: int = 300) -> bool:
        """Пытаемся взять эксклюзивный лок. Возвращает True при успехе.
        Схема: таблица app_locks(app TEXT PK, owner TEXT, expire_at INTEGER).
        """
        expire_at = int(time.time()) + int(ttl_sec)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_locks (
                app TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                expire_at INTEGER NOT NULL
            )
            """
        )
        # попытаться вставить лок, если его нет или истёк — захватить
        cur = self.conn.execute(
            """
            INSERT INTO app_locks(app, owner, expire_at)
            VALUES(?, ?, ?)
            ON CONFLICT(app) DO UPDATE SET
                owner=excluded.owner,
                expire_at=excluded.expire_at
            WHERE app_locks.expire_at < strftime('%s','now')
            """,
            (self.app, self.owner, expire_at),
        )
        # sqlite не даёт rowcount по upsert условно; перепроверь владение
        cur = self.conn.execute("SELECT owner, expire_at FROM app_locks WHERE app=?", (self.app,))
        row = cur.fetchone()
        ok = bool(row and row[0] == self.owner)
        _log.info("lock_acquire", extra={"ok": ok, "owner": self.owner})
        return ok

    def release(self) -> None:
        self.conn.execute("DELETE FROM app_locks WHERE app=? AND owner=?", (self.app, self.owner))
        _log.info("lock_release", extra={"owner": self.owner})