import sqlite3
import time
from typing import Optional, Dict, Any


class SqliteIdempotencyRepository:
    """
    Идемпотентность без гонок.
    Таблица:
      idempotency(
        key TEXT PRIMARY KEY,
        created_ms INTEGER NOT NULL,
        committed INTEGER NOT NULL DEFAULT 0,
        state TEXT
      )

    Протокол:
      claim(key, ttl_seconds) -> True/False  (атомарно «захватывает» слот)
      commit(key, state='ok')                (фиксирует завершение работы)
      get(key) -> dict|None
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        # Страхующая инициализация
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS idempotency(
          key TEXT PRIMARY KEY,
          created_ms INTEGER NOT NULL,
          committed INTEGER NOT NULL DEFAULT 0,
          state TEXT
        );
        """)
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_ms);")

    def claim(self, key: str, ttl_seconds: int = 300) -> bool:
        """
        Атомарный захват ключа:
        1) Пытаемся вставить запись (INSERT OR IGNORE). Если вставилась — наш захват.
        2) Если запись уже была:
             - Если она не зафиксирована и протухла по TTL — забираем «аренду» UPDATE'ом по условию.
             - Иначе — занято.
        """
        now_ms = int(time.time() * 1000)
        ttl_ms = int(ttl_seconds * 1000)

        with self.con:  # транзакция
            cur = self.con.execute(
                "INSERT OR IGNORE INTO idempotency(key, created_ms, committed, state) "
                "VALUES (?, ?, 0, 'claimed')",
                (key, now_ms)
            )
            if cur.rowcount == 1:
                return True  # только что вставили — наш захват

            # запись уже существует — смотрим, можно ли «реанимировать» просроченную незакоммиченную
            cutoff = now_ms - ttl_ms
            cur2 = self.con.execute(
                "UPDATE idempotency "
                "SET created_ms = ?, state = 'claimed' "
                "WHERE key = ? AND committed = 0 AND created_ms < ?",
                (now_ms, key, cutoff)
            )
            return cur2.rowcount == 1  # удалось забрать аренду

    def commit(self, key: str, *, state: str = "ok") -> None:
        with self.con:
            self.con.execute(
                "UPDATE idempotency SET committed = 1, state = ? WHERE key = ?",
                (state, key)
            )

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT key, created_ms, committed, state FROM idempotency WHERE key = ?",
            (key,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"key": row[0], "created_ms": int(row[1]), "committed": int(row[2]), "state": row[3]}
