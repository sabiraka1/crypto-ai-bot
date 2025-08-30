from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone, timedelta

def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)

@dataclass
class IdempotencyRepository:
    conn: Any  # sqlite3.Connection с row_factory=sqlite3.Row

    def check_and_store(self, key: str, ttl_sec: int) -> bool:
        """
        Пытается атомарно зарезервировать ключ идемпотентности.
        true  -> мы владелец (вставка прошла)
        false -> ключ уже существует/свежий
        """
        expire_at = _now_ms() + int(ttl_sec * 1000)
        cur = self.conn.cursor()
        # 1) Удаляем протухшие ключи (в одном запросе, без window race)
        cur.execute("DELETE FROM idempotency WHERE expire_at < ?", ( _now_ms(), ))
        # 2) Пытаемся вставить наш ключ; при конфликте — игнор
        cur.execute(
            "INSERT OR IGNORE INTO idempotency(key, expire_at) VALUES(?, ?)",
            (key, expire_at)
        )
        self.conn.commit()
        return cur.rowcount == 1

    def prune_older_than(self, seconds: int) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM idempotency WHERE expire_at < ?", (_now_ms() - seconds * 1000,))
        self.conn.commit()
