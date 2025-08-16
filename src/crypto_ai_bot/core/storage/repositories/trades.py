from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT,
    ts TEXT NOT NULL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts);
"""

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "position_id": row["position_id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "size": row["size"],
        "price": row["price"],
        "fee": row["fee"],
        "ts": row["ts"],
        "payload": json.loads(row["payload"]) if row["payload"] else None,
    }

class SqliteTradeRepository:
    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.row_factory = sqlite3.Row
        with self.con:
            self.con.executescript(_SCHEMA)

    def insert(self, trade: Dict[str, Any]) -> int:
        with self.con:
            cur = self.con.execute(
                """
                INSERT INTO trades(position_id, symbol, side, size, price, fee, ts, payload)
                VALUES(:position_id, :symbol, :side, :size, :price, :fee, :ts, :payload)
                """,
                {**trade, "payload": json.dumps(trade.get("payload")) if trade.get("payload") is not None else None},
            )
            return int(cur.lastrowid)

    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self.con.execute(
            "SELECT * FROM trades WHERE symbol = ? ORDER BY ts DESC LIMIT ?",
            (symbol, int(limit)),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
