from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)

@dataclass
class IdempotencyRepository:
    conn: Any  # sqlite3.Connection с row_factory=sqlite3.Row

    def ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS idempotency ("
            " key TEXT PRIMARY KEY,"
            " expire_at INTEGER NOT NULL"
            ")"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_idem_expire ON idempotency(expire_at)")
        self.conn.commit()

    def check_and_store(self, key: str, ttl_sec: int) -> bool:
        """
        Атомарно резервирует ключ на ttl_sec.
        True -> ключ зарезервирован нами (вставка прошла)
        False -> ключ уже существует и ещё свежий
        """
        self.ensure_schema()
        now = _now_ms()
        expire_at = now + int(ttl_sec * 1000)

        cur = self.conn.cursor()
        # Удаляем протухшие ключи одним запросом
        cur.execute("DELETE FROM idempotency WHERE expire_at < ?", (now, ))
        # Пытаемся вставить наш ключ (PRIMARY KEY гарантирует уникальность)
        try:
            cur.execute(
                "INSERT OR IGNORE INTO idempotency(key, expire_at) VALUES(?, ?)",
                (key, expire_at)
            )
        finally:
            self.conn.commit()
        return cur.rowcount == 1

    def prune_older_than(self, seconds: int) -> None:
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute("DELETE FROM idempotency WHERE expire_at < ?", (_now_ms() - seconds * 1000, ))
        self.conn.commit()
