# src/crypto_ai_bot/core/storage/repositories/trades.py
import sqlite3
import time
from typing import Dict, Any, List, Optional

class SqliteTradeRepository:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            qty REAL NOT NULL,
            pnl REAL DEFAULT 0.0
        );
        """)

    # ---- совместимость ----
    def insert_trade(self, symbol: str, side: str, price: float, qty: float, pnl: float = 0.0) -> int:
        with self.con:
            cur = self.con.execute(
                "INSERT INTO trades(ts, symbol, side, price, qty, pnl, state) VALUES(?,?,?,?,?,?, 'filled')",
                (int(time.time()), symbol, side, float(price), float(qty), float(pnl))
            )
            return int(cur.lastrowid)

    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, int(limit))
        cur = self.con.execute(
            "SELECT id, ts, symbol, side, price, qty, pnl, order_id, state, fee_amt, fee_ccy "
            "FROM trades WHERE symbol = ? ORDER BY ts DESC LIMIT ?",
            (symbol, limit)
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ---- FSM ----
    def create_pending_order(self, *, symbol: str, side: str, exp_price: float, qty: float, order_id: str) -> int:
        with self.con:
            cur = self.con.execute(
                "INSERT INTO trades(ts, symbol, side, price, qty, pnl, order_id, state) VALUES(?,?,?,?,?,?,?, 'pending')",
                (int(time.time()), symbol, side, float(exp_price), float(qty), 0.0, order_id)
            )
            return int(cur.lastrowid)

    def update_order_state(self, *, order_id: str, state: str) -> None:
        with self.con:
            self.con.execute("UPDATE trades SET state=? WHERE order_id=?", (state, order_id,))

    def fill_order(self, *, order_id: str, executed_price: float, executed_qty: float, fee_amt: float = 0.0, fee_ccy: str = "USDT") -> None:
        with self.con:
            self.con.execute(
                "UPDATE trades SET state='filled', price=?, qty=?, fee_amt=?, fee_ccy=? WHERE order_id=?",
                (float(executed_price), float(executed_qty), float(fee_amt), fee_ccy, order_id)
            )

    def cancel_order(self, *, order_id: str) -> None:
        with self.con:
            self.con.execute("UPDATE trades SET state='canceled' WHERE order_id=?", (order_id,))

    def reject_order(self, *, order_id: str) -> None:
        with self.con:
            self.con.execute("UPDATE trades SET state='rejected' WHERE order_id=?", (order_id,))

    def find_pending_orders(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        q = "SELECT id, ts, symbol, side, price, qty, order_id FROM trades WHERE state='pending'"
        p: List[Any] = []
        if symbol:
            q += " AND symbol=?"
            p.append(symbol)
        q += " ORDER BY ts ASC LIMIT ?"
        p.append(max(1, int(limit)))
        cur = self.con.execute(q, tuple(p))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def count_pending(self) -> int:
        cur = self.con.execute("SELECT COUNT(1) FROM trades WHERE state='pending'")
        (n,) = cur.fetchone() or (0,)
        return int(n)
