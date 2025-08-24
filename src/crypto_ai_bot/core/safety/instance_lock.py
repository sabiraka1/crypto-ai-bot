from __future__ import annotations

import os
import sqlite3
from typing import Optional
from ...utils.time import now_ms
from ...utils.logging import get_logger

class InstanceLock:
    """
    DB-based single instance lock.
    Таблица создаётся при первом использовании.
    """

    def __init__(self, conn: sqlite3.Connection, name: str) -> None:
        self._log = get_logger("safety.lock")
        self._c = conn
        self._name = name
        self._owner = f"pid-{os.getpid()}"
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._c.execute("""
        CREATE TABLE IF NOT EXISTS locks(
            app TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            acquired_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL
        )""")
        self._c.commit()

    def acquire(self, *, ttl_sec: int = 300) -> bool:
        now = now_ms()
        exp = now + ttl_sec * 1000
        # UPSERT: если лока нет — вставим; если есть, обновим только если просрочен
        try:
            self._c.execute("""
            INSERT INTO locks(app, owner, acquired_at_ms, expires_at_ms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(app) DO UPDATE SET
              owner=excluded.owner,
              acquired_at_ms=excluded.acquired_at_ms,
              expires_at_ms=excluded.expires_at_ms
            WHERE locks.expires_at_ms < ?
            """, (self._name, self._owner, now, exp, now))
            self._c.commit()
            # проверим, что владелец — мы
            row = self._c.execute("SELECT owner, expires_at_ms FROM locks WHERE app=?", (self._name,)).fetchone()
            return bool(row and row["owner"] == self._owner)
        except Exception as exc:
            self._log.error("acquire_failed", extra={"error": str(exc)})
            return False

    def heartbeat(self, *, ttl_sec: int = 300) -> None:
        now = now_ms()
        exp = now + ttl_sec * 1000
        self._c.execute("""
        UPDATE locks SET acquired_at_ms=?, expires_at_ms=?, owner=?
        WHERE app=? AND owner=?""", (now, exp, self._owner, self._name, self._owner))
        self._c.commit()

    def release(self) -> None:
        self._c.execute("DELETE FROM locks WHERE app=? AND owner=?", (self._name, self._owner))
        self._c.commit()
