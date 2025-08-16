from __future__ import annotations
import sqlite3, time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..interfaces import PositionRepository

CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS positions(
  symbol TEXT PRIMARY KEY,
  size   TEXT NOT NULL,
  avg_price TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_updated ON positions(updated_at);
'''

class SqlitePositionRepository(PositionRepository):
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.executescript(CREATE_SQL)

    def get_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        cur = self.con.execute("SELECT symbol,size,avg_price,updated_at FROM positions WHERE symbol=?;", (symbol,))
        row = cur.fetchone()
        if not row: return None
        return {
            "symbol": row[0],
            "size": Decimal(row[1]),
            "avg_price": Decimal(row[2]),
            "updated_at": int(row[3]),
        }

    def get_open(self) -> List[Dict[str, Any]]:
        cur = self.con.execute("SELECT symbol,size,avg_price,updated_at FROM positions WHERE CAST(size AS REAL) != 0;")
        return [{
            "symbol": r[0],
            "size": Decimal(r[1]),
            "avg_price": Decimal(r[2]),
            "updated_at": int(r[3]),
        } for r in cur.fetchall()]

    def save(self, symbol: str, size: Decimal, avg_price: Decimal) -> None:
        now = int(time.time() * 1000)
        self.con.execute(
            "INSERT INTO positions(symbol,size,avg_price,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET size=excluded.size, avg_price=excluded.avg_price, updated_at=excluded.updated_at;",
            (symbol, str(size), str(avg_price), now),
        )

    def close_all(self, symbol: str) -> Dict[str, Any]:
        now = int(time.time() * 1000)
        self.con.execute(
            "INSERT INTO positions(symbol,size,avg_price,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET size='0', avg_price=excluded.avg_price, updated_at=excluded.updated_at;",
            (symbol, '0', '0', now),
        )
        return {"symbol": symbol, "size": "0", "avg_price": "0", "updated_at": now}
