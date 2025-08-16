from __future__ import annotations

import sqlite3
import time
import json
from dataclasses import dataclass
from typing import Optional, Any

@dataclass
class IdempotencyRecord:
    key: str
    created_ms: int
    payload: bytes | None = None

def build_key(symbol: str, side: str, size: str, ts_ms: int, decision_id: str) -> str:
    """
    Ключ строго по спецификации:
    {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
    """
    minute = int(ts_ms // 60000)
    return f"{symbol}:{side}:{size}:{minute}:{str(decision_id)[:8]}"

class SqliteIdempotencyRepository:
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        # мягкое создание таблицы, если миграция не прогнана
        with self.con:
            self.con.execute("""
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    created_ms INTEGER NOT NULL,
                    payload BLOB
                );
            """)

    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        now_ms = int(time.time() * 1000)
        with self.con:
            self.con.execute("DELETE FROM idempotency WHERE created_ms < ?", (now_ms - ttl_seconds * 1000,))
            cur = self.con.execute("SELECT 1 FROM idempotency WHERE key = ?", (key,))
            if cur.fetchone():
                return False
            self.con.execute("INSERT INTO idempotency(key, created_ms) VALUES(?, ?)", (key, now_ms))
            return True

    def commit(self, key: str, payload: bytes | None = None) -> None:
        with self.con:
            self.con.execute("UPDATE idempotency SET payload = ? WHERE key = ?", (payload, key))

    def release(self, key: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM idempotency WHERE key = ?", (key,))

    def get_original_payload(self, key: str) -> Optional[bytes]:
        cur = self.con.execute("SELECT payload FROM idempotency WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        return row[0]

    def get_original_order(self, key: str) -> Optional[dict]:
        """Попытаться декодировать payload как JSON с исходным ответом брокера/позиции."""
        blob = self.get_original_payload(key)
        if not blob:
            return None
        try:
            if isinstance(blob, memoryview):
                blob = blob.tobytes()
            return json.loads(blob.decode("utf-8"))
        except Exception:
            return None

    def check_and_store(self, key: str, payload: bytes | None = None, ttl_seconds: int = 300) -> bool:
        if not self.claim(key, ttl_seconds=ttl_seconds):
            return False
        self.commit(key, payload=payload)
        return True
