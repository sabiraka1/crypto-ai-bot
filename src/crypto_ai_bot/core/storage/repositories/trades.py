from __future__ import annotations
import sqlite3, time, json
from decimal import Decimal
from typing import Any, Dict, List

from ..interfaces import TradeRepository

CREATE_SQL = '''
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  size TEXT NOT NULL,
  price TEXT NOT NULL,
  meta  TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts DESC);
'''

class SqliteTradeRepository(TradeRepository):
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.executescript(CREATE_SQL)

    def insert(self, trade: Dict[str, Any]) -> None:
        ts = int(trade.get("ts") or time.time() * 1000)
        self.con.execute(
            "INSERT INTO trades(ts,symbol,side,size,price,meta) VALUES(?,?,?,?,?,?);",
            (
                ts,
                trade["symbol"],
                trade["side"],
                str(Decimal(str(trade["size"]))),
                str(Decimal(str(trade["price"]))),
                json.dumps(trade.get("meta") or {}),
            ),
        )

    def list_by_symbol(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT id,ts,symbol,side,size,price,meta FROM trades WHERE symbol=? ORDER BY ts DESC LIMIT ?;",
            (symbol, int(limit)),
        )
        out = []
        for row in cur.fetchall():
            out.append({
                "id": int(row[0]),
                "ts": int(row[1]),
                "symbol": row[2],
                "side": row[3],
                "size": row[4],
                "price": row[5],
                "meta": json.loads(row[6] or "{}"),
            })
        return out
