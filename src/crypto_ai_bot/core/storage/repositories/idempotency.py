from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from crypto_ai_bot.utils import metrics

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    status TEXT NOT NULL,            -- 'pending' | 'committed'
    order_ref TEXT,
    payload TEXT,
    created_at TEXT NOT NULL,        -- ISO UTC
    expires_at TEXT NOT NULL         -- ISO UTC
);
CREATE INDEX IF NOT EXISTS ix_idemp_expires ON idempotency_keys(expires_at);
"""

@dataclass
class IdempotencyRecord:
    key: str
    status: str
    order_ref: Optional[str]
    payload: Optional[str]
    created_at: str
    expires_at: str

class IdempotencyRepository:
    """
    SQLite-backed идемпотентность:
      - claim(key, ttl_sec) -> bool
      - commit(key, order_ref_json) -> None
      - release(key) -> None
      - get_original_order(key) -> Optional[str]
      - check_and_store(key, ttl_sec, payload_json=None) -> (ok_new: bool, existing_ref: Optional[str])
      - purge_expired() -> int
      - count_active() -> int
    """
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._con.executescript(TABLE_SQL)
        self._con.commit()

    @contextmanager
    def _txn(self):
        cur = self._con.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            try:
                yield cur
                self._con.commit()
            except Exception:
                self._con.rollback()
                raise
        finally:
            cur.close()

    def purge_expired(self) -> int:
        """Удаляет просроченные записи. Возвращает кол-во удалённых."""
        now_iso = datetime.now(timezone.utc).isoformat()
        cur = self._con.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (now_iso,))
        n = cur.rowcount if cur.rowcount is not None else 0
        if n:
            metrics.inc("idempotency_purged_total", {"count": n})
        return n

    def count_active(self) -> int:
        """Количество активных (не истёкших) ключей, независимо от статуса."""
        now_iso = datetime.now(timezone.utc).isoformat()
        row = self._con.execute("SELECT COUNT(1) FROM idempotency_keys WHERE expires_at >= ?", (now_iso,)).fetchone()
        return int(row[0] if row and row[0] is not None else 0)

    def fetch(self, key: str) -> Optional[IdempotencyRecord]:
        row = self._con.execute(
            "SELECT key, status, order_ref, payload, created_at, expires_at FROM idempotency_keys WHERE key=?",
            (key,)
        ).fetchone()
        if not row:
            return None
        return IdempotencyRecord(*row)

    def claim(self, key: str, ttl_sec: int, *, payload_json: Optional[str] = None) -> bool:
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=max(1, int(ttl_sec)))
        now_iso, exp_iso = now.isoformat(), exp.isoformat()

        with self._txn() as cur:
            cur.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (now_iso,))
            try:
                cur.execute(
                    "INSERT INTO idempotency_keys(key, status, order_ref, payload, created_at, expires_at) "
                    "VALUES (?, 'pending', NULL, ?, ?, ?)",
                    (key, payload_json, now_iso, exp_iso)
                )
                metrics.inc("idempotency_claim_total", {})
                return True
            except sqlite3.IntegrityError:
                metrics.inc("idempotency_conflicts_total", {})
                return False

    def commit(self, key: str, order_ref_json: str) -> None:
        with self._txn() as cur:
            cur.execute(
                "UPDATE idempotency_keys SET status='committed', order_ref=? WHERE key=?",
                (order_ref_json, key)
            )
            metrics.inc("idempotency_commit_total", {})

    def release(self, key: str) -> None:
        with self._txn() as cur:
            cur.execute("DELETE FROM idempotency_keys WHERE key=?", (key,))
            metrics.inc("idempotency_release_total", {})

    def get_original_order(self, key: str) -> Optional[str]:
        rec = self.fetch(key)
        if not rec:
            return None
        return rec.order_ref

    def check_and_store(self, key: str, ttl_sec: int, *, payload_json: Optional[str] = None):
        ok = self.claim(key, ttl_sec, payload_json=payload_json)
        if ok:
            return True, None
        ref = self.get_original_order(key)
        metrics.inc("idempotency_hits_total", {"has_ref": str(ref is not None).lower()})
        return False, ref
