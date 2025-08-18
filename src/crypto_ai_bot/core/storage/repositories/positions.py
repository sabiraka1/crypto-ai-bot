from __future__ import annotations
import sqlite3
from typing import List, Dict, Any, Optional

DDL = """
CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL UNIQUE,
  qty REAL NOT NULL DEFAULT 0,
  avg_price REAL NOT NULL DEFAULT 0
);
"""

class SqlitePositionRepository:
    """Храним свернутые позиции; поддерживаем ресинк из trades."""
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute(DDL)

    def get_open(self) -> List[Dict[str, Any]]:
        cur = self.con.execute("SELECT symbol, qty, avg_price FROM positions WHERE qty > 0")
        return [{"symbol": s, "qty": float(q), "avg_price": float(ap)} for (s, q, ap) in cur.fetchall()]

    def has_long(self, symbol: str) -> bool:
        cur = self.con.execute("SELECT 1 FROM positions WHERE symbol=? AND qty>0", (symbol,))
        return cur.fetchone() is not None

    def long_qty(self, symbol: str) -> float:
        cur = self.con.execute("SELECT qty FROM positions WHERE symbol=?", (symbol,))
        row = cur.fetchone()
        return float(row[0]) if row else 0.0

    # --- поддержка консистентности с фактами из trades ---

    def recompute_from_trades(self, symbol: Optional[str] = None) -> None:
        """
        Сворачиваем filled/partial_filled трейды в агрегированную позицию.
        Важно вызывать периодически из reconciler либо после серии ордеров.
        """
        if symbol:
            syms = [symbol]
        else:
            cur = self.con.execute("SELECT DISTINCT symbol FROM trades WHERE state IN ('filled','partial_filled')")
            syms = [r[0] for r in cur.fetchall()]

        for sym in syms:
            cur = self.con.execute(
                "SELECT side, price, qty, COALESCE(fee_amt,0.0) "
                "FROM trades WHERE symbol=? AND state IN ('filled','partial_filled') ORDER BY ts ASC",
                (sym,)
            )
            qty = 0.0
            avg = 0.0
            for (side, price, q, fee) in cur.fetchall():
                price = float(price); q = float(q)
                if side == "buy":
                    new_qty = qty + q
                    avg = (avg * qty + price * q) / new_qty if new_qty > 0 else 0.0
                    qty = new_qty
                else:
                    sell_qty = min(q, qty)
                    qty = max(0.0, qty - sell_qty)
                    if qty == 0.0:
                        avg = 0.0
            with self.con:
                if qty <= 0:
                    self.con.execute("DELETE FROM positions WHERE symbol=?", (sym,))
                else:
                    self.con.execute(
                        "INSERT INTO positions(symbol, qty, avg_price) VALUES(?,?,?) "
                        "ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price",
                        (sym, qty, avg)
                    )
