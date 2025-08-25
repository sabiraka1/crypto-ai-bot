from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from ...utils.time import now_ms
from ...utils.logging import get_logger


@dataclass
class InstanceLock:
    """
    Простой DB-based single-instance lock.

    Таблица: locks(app TEXT PRIMARY KEY, owner TEXT, acquired_at_ms INT, expires_at_ms INT)

    Использование:
      lock = InstanceLock(conn, app="trader", owner="host123")
      ok = lock.acquire(ttl_sec=300)
      if ok: lock.heartbeat(ttl_sec=300) периодически
      finally: lock.release()
    """
    conn: sqlite3.Connection
    app: str
    owner: str

    def __post_init__(self) -> None:
        self._log = get_logger("safety.instance_lock")

    def acquire(self, ttl_sec: int = 300) -> bool:
        """Пытается захватить лок. true — лок наш; false — лок уже у другого и ещё не истёк."""
        now = now_ms()
        expires = now + ttl_sec * 1000
        cur = self.conn.cursor()
        try:
            # зачистить протухший лок (если владелец умер)
            cur.execute(
                "DELETE FROM locks WHERE app = ? AND expires_at_ms < ?",
                (self.app, now),
            )
            # вставить наш лок, если свободно
            cur.execute(
                """
                INSERT OR IGNORE INTO locks (app, owner, acquired_at_ms, expires_at_ms)
                VALUES (?, ?, ?, ?)
                """,
                (self.app, self.owner, now, expires),
            )
            self.conn.commit()
            got = cur.rowcount > 0
            if got:
                self._log.info("lock_acquired", extra={"app": self.app, "owner": self.owner})
            else:
                self._log.info("lock_busy", extra={"app": self.app})
            return got
        finally:
            cur.close()

    def heartbeat(self, ttl_sec: int = 300) -> None:
        """Продлевает наш лок (если мы владелец). Безошибочно, если лок не наш — молча игнорирует."""
        now = now_ms()
        expires = now + ttl_sec * 1000
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                UPDATE locks
                   SET expires_at_ms = ?
                 WHERE app = ? AND owner = ?
                """,
                (expires, self.app, self.owner),
            )
            self.conn.commit()
        finally:
            cur.close()

    def release(self) -> None:
        """Отпускает лок, но только если мы владелец."""
        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM locks WHERE app = ? AND owner = ?", (self.app, self.owner))
            self.conn.commit()
            self._log.info("lock_released", extra={"app": self.app, "owner": self.owner})
        finally:
            cur.close()
