# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

from crypto_ai_bot.core.storage.interfaces import (
    IdempotencyRepository, IdemStatus, StorageError,
)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  state TEXT NOT NULL,              -- 'claimed' | 'committed'
  created_at INTEGER NOT NULL,      -- epoch seconds
  ttl_seconds INTEGER NOT NULL,
  payload TEXT                      -- optional JSON
);
CREATE INDEX IF NOT EXISTS ix_idem_state ON idempotency_keys(state);
"""

@dataclass
class IdempotencyRepositorySQLite(IdempotencyRepository):
    conn: sqlite3.Connection

    def __post_init__(self):
        cur = self.conn.cursor()
        # Включай WAL в sqlite_adapter.connect(); здесь — только таблица
        for stmt in filter(bool, _CREATE_SQL.split(";")):
            cur.execute(stmt)
        self.conn.commit()

    def _now(self) -> int:
        return int(time.time())

    def purge_expired(self) -> int:
        now = self._now()
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM idempotency_keys WHERE (? - created_at) >= ttl_seconds",
            (now,),
        )
        self.conn.commit()
        return cur.rowcount

    def claim(self, key: str, ttl_seconds: int, payload: dict | None = None) -> bool:
        now = self._now()
        cur = self.conn.cursor()
        # Удаляем истёкший ключ, если есть
        cur.execute(
            "SELECT created_at, ttl_seconds FROM idempotency_keys WHERE key=?",
            (key,),
        )
        row = cur.fetchone()
        if row:
            created_at, ttl = row
            if (now - int(created_at)) < int(ttl):
                # активен — дубликат
                return False
            # истёк — освобождаем
            cur.execute("DELETE FROM idempotency_keys WHERE key=?", (key,))

        cur.execute(
            "INSERT OR REPLACE INTO idempotency_keys(key, state, created_at, ttl_seconds, payload) "
            "VALUES(?, 'claimed', ?, ?, ?)",
            (key, now, int(ttl_seconds), json.dumps(payload or {})),
        )
        self.conn.commit()
        return True

    def commit(self, key: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE idempotency_keys SET state='committed' WHERE key=?",
            (key,),
        )
        if cur.rowcount == 0:
            # commit без claim — не считаем фаталом, но сообщим
            pass
        self.conn.commit()

    def release(self, key: str) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM idempotency_keys WHERE key=?", (key,))
        self.conn.commit()

    def exists_active(self, key: str) -> bool:
        now = self._now()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT created_at, ttl_seconds FROM idempotency_keys WHERE key=?",
            (key,),
        )
        row = cur.fetchone()
        if not row:
            return False
        created_at, ttl = row
        return (now - int(created_at)) < int(ttl)

    def get(self, key: str) -> Optional[IdemStatus]:
        now = self._now()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT state, created_at, ttl_seconds FROM idempotency_keys WHERE key=?",
            (key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        state, created_at, ttl = row
        if (now - int(created_at)) >= int(ttl):
            return None
        return IdemStatus(key=key, state=str(state), ttl_seconds=int(ttl))
