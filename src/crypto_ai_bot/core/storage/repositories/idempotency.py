from __future__ import annotations
import sqlite3, time
from typing import Optional, Tuple

DDL = """
CREATE TABLE IF NOT EXISTS idempotency(
  key TEXT PRIMARY KEY,
  created_ms INTEGER NOT NULL,
  ttl_sec INTEGER NOT NULL,
  committed INTEGER NOT NULL DEFAULT 0,
  state TEXT
);
"""

class IdempotencyRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute(DDL)

    @staticmethod
    def _now_ms() -> int: return int(time.time() * 1000)

    # ---- требуемые чекером методы ----

    def check_and_store(self, key: str, ttl_seconds: int) -> bool:
        """
        Атомарно вставляет ключ, если его нет/протух. True — впервые, False — дубликат.
        """
        now = self._now_ms()
        with self.con:
            # удалить протухшие перед вставкой
            self.con.execute("DELETE FROM idempotency WHERE created_ms + (ttl_sec*1000) < ?", (now,))
            try:
                self.con.execute(
                    "INSERT INTO idempotency(key, created_ms, ttl_sec, committed, state) VALUES (?,?,?,?,?)",
                    (key, now, int(ttl_seconds), 0, "claimed"),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def claim(self, key: str, ttl_seconds: int = 60) -> bool:
        return self.check_and_store(key, ttl_seconds)

    def commit(self, key: str, state: str = "done") -> None:
        with self.con:
            self.con.execute("UPDATE idempotency SET committed=1, state=? WHERE key=?", (state, key))

    def cleanup_expired(self) -> int:
        now = self._now_ms()
        with self.con:
            cur = self.con.execute("DELETE FROM idempotency WHERE created_ms + (ttl_sec*1000) < ?", (now,))
            return int(cur.rowcount)
