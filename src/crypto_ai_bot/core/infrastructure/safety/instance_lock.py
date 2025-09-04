from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import sys
import time

from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("safety.lock")


@dataclass
class InstanceLock:
    conn: sqlite3.Connection
    app: str
    owner: str

    def acquire(self, ttl_sec: int = 300) -> bool:
        """Пытаемся установить эксклюзивный лок в SQLite."""
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
        cur = self.conn.execute("SELECT owner, expire_at FROM app_locks WHERE app=?", (self.app,))
        row = cur.fetchone()
        ok = bool(row and row[0] == self.owner)
        _log.info("lock_acquire", extra={"ok": ok, "owner": self.owner})
        return ok

    def release(self) -> None:
        self.conn.execute("DELETE FROM app_locks WHERE app=? AND owner=?", (self.app, self.owner))
        _log.info("lock_release", extra={"owner": self.owner})


def create_instance_lock(app: str, owner: str, path: str = "instance.lock.db") -> InstanceLock:
    conn = sqlite3.connect(path, check_same_thread=False)
    lock = InstanceLock(conn, app, owner)
    if not lock.acquire():
        _log.error("Another instance is already running", extra={"app": app})
        sys.exit(1)
    return lock
