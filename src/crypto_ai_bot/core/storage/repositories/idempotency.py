from __future__ import annotations
import sqlite3, time, json
from typing import Any, Dict, Optional

from ..interfaces import IdempotencyRepository

CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS idempotency(
  key TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_at DESC);
'''

class SqliteIdempotencyRepository(IdempotencyRepository):
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.executescript(CREATE_SQL)

    def claim(self, key: str) -> bool:
        try:
            self.con.execute(
                "INSERT INTO idempotency(key,created_at,status,result_json) VALUES(?,?,?,?);",
                (key, int(time.time()*1000), "claimed", None),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def commit(self, key: str, result: Dict[str, Any]) -> None:
        self.con.execute(
            "UPDATE idempotency SET status='committed', result_json=? WHERE key=?;",
            (json.dumps(result, ensure_ascii=False), key),
        )

    def release(self, key: str) -> None:
        self.con.execute("DELETE FROM idempotency WHERE key=?;", (key,))
