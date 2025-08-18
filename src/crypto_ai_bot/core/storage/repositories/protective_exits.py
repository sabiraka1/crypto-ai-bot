import sqlite3
import time
from typing import List, Dict, Any, Optional

class SqliteProtectiveExitsRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        # Таблица создаётся миграцией, но дублируем защитно
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS protective_exits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          position_id INTEGER,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,        -- 'sell' (long-only выходы)
          kind TEXT NOT NULL,        -- 'sl' | 'tp'
          trigger_px REAL NOT NULL,
          created_ts INTEGER NOT NULL,
          active INTEGER NOT NULL DEFAULT 1
        );
        """)

    def upsert(
        self,
        *,
        position_id: Optional[int],
        symbol: str,
        side: str,
        kind: str,
        trigger_px: float
    ) -> int:
        with self.con:
            cur = self.con.execute(
                "INSERT INTO protective_exits(position_id, symbol, side, kind, trigger_px, created_ts, active) "
                "VALUES(?,?,?,?,?,?, 1)",
                (position_id, symbol, side, kind, float(trigger_px), int(time.time()))
            )
            return int(cur.lastrowid)

    def list_active(self, symbol: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        q = ("SELECT id, position_id, symbol, side, kind, trigger_px, created_ts "
             "FROM protective_exits WHERE active=1")
        params: list[Any] = []
        if symbol:
            q += " AND symbol=?"
            params.append(symbol)
        q += " ORDER BY created_ts ASC LIMIT ?"
        params.append(max(1, int(limit)))
        cur = self.con.execute(q, tuple(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def deactivate(self, exit_id: int) -> None:
        with self.con:
            self.con.execute("UPDATE protective_exits SET active=0 WHERE id=?", (exit_id,))
