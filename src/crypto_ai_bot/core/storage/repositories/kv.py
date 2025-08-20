# src/crypto_ai_bot/core/storage/repositories/kv.py
"""
Простейшее KV-хранилище поверх SQLite (append-like upsert).
Используется для «heartbeat» и прочих лёгких служебных флагов.
"""

from __future__ import annotations
import sqlite3
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_ms INTEGER NOT NULL
);
"""


class SqliteKVRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(_SCHEMA)
        self.conn.commit()

    def set(self, key: str, value: str, updated_ms: Optional[int] = None) -> None:
        from datetime import datetime, timezone
        if updated_ms is None:
            updated_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO kv(key, value, updated_ms) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ms=excluded.updated_ms",
            (key, value, int(updated_ms)),
        )
        self.conn.commit()

    def get(self, key: str) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def get_with_timestamp(self, key: str) -> Optional[tuple[str, int]]:
        cur = self.conn.cursor()
        cur.execute("SELECT value, updated_ms FROM kv WHERE key = ?", (key,))
        row = cur.fetchone()
        return (row[0], int(row[1])) if row else None
