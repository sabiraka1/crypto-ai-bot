# src/crypto_ai_bot/core/storage/repositories/idempotency.py
from __future__ import annotations
import sqlite3
import time
from typing import Optional, Tuple

from crypto_ai_bot.core.storage.interfaces import IdempotencyRepository


class SqliteIdempotencyRepository(IdempotencyRepository):  # type: ignore[misc]
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def purge_expired(self) -> int:
        now = self._now_ms()
        cur = self._con.execute("DELETE FROM idempotency WHERE expires_at <= ?;", (now,))
        return cur.rowcount or 0

    def claim(self, key: str, ttl_seconds: int) -> bool:
        now = self._now_ms()
        exp = now + int(ttl_seconds * 1000)
        cur = self._con.execute("SELECT state, expires_at FROM idempotency WHERE key = ?;", (key,))
        row = cur.fetchone()
        if row is None or int(row["expires_at"]) <= now:
            self._con.execute(
                """
                INSERT INTO idempotency(key, state, expires_at, updated_at, payload_json)
                VALUES(?, 'claimed', ?, ?, NULL)
                ON CONFLICT(key) DO UPDATE SET
                    state='claimed',
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
                """,
                (key, exp, now),
            )
            return True
        return False

    def check_and_store(self, key: str, payload_json: str, ttl_seconds: int) -> Tuple[bool, Optional[str]]:
        """Если ключ свободен или истёк — захватываем и кладём payload_json.
        Если ключ активен — возвращаем (False, существующий payload_json/None).
        """
        now = self._now_ms()
        exp = now + int(ttl_seconds * 1000)
        cur = self._con.execute("SELECT state, expires_at, payload_json FROM idempotency WHERE key = ?;", (key,))
        row = cur.fetchone()
        if row is None or int(row["expires_at"]) <= now:
            self._con.execute(
                """
                INSERT INTO idempotency(key, state, expires_at, updated_at, payload_json)
                VALUES(?, 'claimed', ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    state='claimed',
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (key, exp, now, payload_json),
            )
            return True, None
        return False, row["payload_json"]

    def commit(self, key: str, payload_json: Optional[str] = None) -> None:
        now = self._now_ms()
        self._con.execute(
            """
            UPDATE idempotency
               SET state='committed',
                   expires_at=?,
                   updated_at=?,
                   payload_json=COALESCE(?, payload_json)
             WHERE key=?;
            """,
            (now + 24 * 3600 * 1000, now, payload_json, key),
        )

    def release(self, key: str) -> None:
        self._con.execute("DELETE FROM idempotency WHERE key = ?;", (key,))

    def get_original_order(self, key: str) -> Optional[str]:
        cur = self._con.execute("SELECT payload_json FROM idempotency WHERE key = ?;", (key,))
        row = cur.fetchone()
        return row["payload_json"] if row else None
