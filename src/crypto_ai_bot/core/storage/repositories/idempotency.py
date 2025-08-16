from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional, Tuple


class SqliteIdempotencyRepository:
    """
    SQLite идемпотентность с авто-миграцией схемы.
    """
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self._ensure_schema()

    # ---------- schema & migrations ----------
    def _has_column(self, table: str, col: str) -> bool:
        cur = self.con.execute(f"PRAGMA table_info({table})")
        return any(r[1] == col for r in cur.fetchall())

    def _ensure_schema(self) -> None:
        # Базовая таблица
        self.con.execute("CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY);")
        # Эволюция столбцов
        if not self._has_column("idempotency", "payload"):
            self.con.execute("ALTER TABLE idempotency ADD COLUMN payload TEXT NULL;")
        if not self._has_column("idempotency", "result"):
            self.con.execute("ALTER TABLE idempotency ADD COLUMN result TEXT NULL;")
        if not self._has_column("idempotency", "created_ms"):
            self.con.execute("ALTER TABLE idempotency ADD COLUMN created_ms INTEGER NOT NULL DEFAULT 0;")
            now_ms = int(time.time() * 1000)
            self.con.execute("UPDATE idempotency SET created_ms = CASE WHEN created_ms=0 THEN ? ELSE created_ms END;", (now_ms,))
        if not self._has_column("idempotency", "committed"):
            self.con.execute("ALTER TABLE idempotency ADD COLUMN committed INTEGER NOT NULL DEFAULT 0;")
        if not self._has_column("idempotency", "updated_ms"):
            self.con.execute("ALTER TABLE idempotency ADD COLUMN updated_ms INTEGER NULL;")
        # Индексы
        try:
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_ms);")
        except sqlite3.OperationalError:
            pass
        try:
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_idem_committed ON idempotency(committed);")
        except sqlite3.OperationalError:
            pass

    # ---------- primitives ----------
    def purge_expired(self, ttl_seconds: int) -> int:
        now_ms = int(time.time() * 1000)
        threshold = now_ms - ttl_seconds * 1000
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE created_ms < ?", (threshold,))
            return cur.rowcount or 0

    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        """
        Пытаемся захватить ключ. True — если запись вставлена впервые.
        Используем INSERT OR IGNORE, чтобы не падать на IntegrityError.
        """
        self.purge_expired(ttl_seconds)
        now_ms = int(time.time() * 1000)
        with self.con:
            cur = self.con.execute(
                "INSERT OR IGNORE INTO idempotency(key, created_ms, committed) VALUES (?, ?, 0)",
                (key, now_ms),
            )
            return (cur.rowcount or 0) == 1

    def commit(self, key: str, result: Dict[str, Any]) -> None:
        now_ms = int(time.time() * 1000)
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET result = ?, committed = 1, updated_ms = ? WHERE key = ?",
                (self._to_json(result), now_ms, key),
            )

    def release(self, key: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM idempotency WHERE key = ?", (key,))

    def get_original(self, key: str) -> Optional[Dict[str, Any]]:
        row = self.con.execute(
            "SELECT payload, result, committed, created_ms, updated_ms FROM idempotency WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        payload, result, committed, created_ms, updated_ms = row
        return {
            "payload": self._from_json(payload),
            "result": self._from_json(result),
            "committed": bool(committed),
            "created_ms": int(created_ms),
            "updated_ms": int(updated_ms) if updated_ms is not None else None,
        }

    def check_and_store(self, key: str, payload_json: str, ttl_seconds: int = 300) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if self.claim(key, ttl_seconds=ttl_seconds):
            now_ms = int(time.time() * 1000)
            with self.con:
                self.con.execute(
                    "UPDATE idempotency SET payload = ?, updated_ms = ? WHERE key = ?",
                    (payload_json, now_ms, key),
                )
            return True, None
        else:
            return False, self.get_original(key)

    # ---------- helpers ----------
    @staticmethod
    def _to_json(obj: Any) -> str:
        if obj is None:
            return "null"
        if isinstance(obj, str):
            return obj
        import json
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _from_json(s: Any) -> Any:
        if s is None:
            return None
        if isinstance(s, (bytes, bytearray)):
            s = s.decode("utf-8", "ignore")
        if isinstance(s, str):
            s = s.strip()
            if s == "" or s == "null":
                return None
            import json
            try:
                return json.loads(s)
            except Exception:
                return s
        return s
