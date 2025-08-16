from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    size TEXT NOT NULL,
    sl TEXT,
    tp TEXT,
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    avg_price TEXT
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
"""


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "size": row["size"],
        "sl": row["sl"],
        "tp": row["tp"],
        "status": row["status"],
        "opened_at": row["opened_at"],
        "closed_at": row["closed_at"],
        "avg_price": row["avg_price"],
    }


class SqlitePositionRepository:
    """Минимальная реализация репозитория позиций для manager.py"""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.row_factory = sqlite3.Row  # удобнее возвращать dict
        with self.con:
            self.con.executescript(_SCHEMA)

    # Принимаем dict из manager.open()/close()/partial_close()
    def upsert(self, pos: Dict[str, Any]) -> None:
        with self.con:
            self.con.execute(
                """
                INSERT INTO positions(id, symbol, side, size, sl, tp, status, opened_at, closed_at, avg_price)
                VALUES(:id, :symbol, :side, :size, :sl, :tp, :status, :opened_at, :closed_at, :avg_price)
                ON CONFLICT(id) DO UPDATE SET
                    symbol=excluded.symbol,
                    side=excluded.side,
                    size=excluded.size,
                    sl=excluded.sl,
                    tp=excluded.tp,
                    status=excluded.status,
                    opened_at=excluded.opened_at,
                    closed_at=excluded.closed_at,
                    avg_price=excluded.avg_price
                """,
                pos,
            )

    def get_by_id(self, pos_id: str) -> Optional[Dict[str, Any]]:
        cur = self.con.execute("SELECT * FROM positions WHERE id = ? LIMIT 1", (pos_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def get_open(self) -> List[Dict[str, Any]]:
        cur = self.con.execute("SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at ASC")
        return [_row_to_dict(r) for r in cur.fetchall()]
