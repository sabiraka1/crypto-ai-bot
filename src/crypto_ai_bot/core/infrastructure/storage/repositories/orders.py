from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass
class OrdersRepository:
    conn: Any  # sqlite3.Connection

    def ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS orders ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " broker_order_id TEXT,"
            " client_order_id TEXT,"
            " symbol TEXT NOT NULL,"
            " side TEXT NOT NULL,"
            " amount TEXT NOT NULL,"
            " filled TEXT NOT NULL DEFAULT '0',"
            " status TEXT NOT NULL DEFAULT 'open',"
            " ts_ms INTEGER NOT NULL"
            ")"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        self.conn.commit()

    def upsert_open(self, order: Any) -> None:
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO orders (broker_order_id, client_order_id, symbol, side, amount, filled, status, ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                getattr(order, "id", None) or getattr(order, "order_id", None),
                getattr(order, "client_order_id", None),
                getattr(order, "symbol", None),
                getattr(order, "side", None),
                str(getattr(order, "amount", "0")),
                str(getattr(order, "filled", "0")),
                getattr(order, "status", "open") or "open",
                int(getattr(order, "ts_ms", 0)),
            ),
        )
        self.conn.commit()

    def list_open(self, symbol: str) -> list[dict]:
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, broker_order_id, client_order_id, symbol, side, amount, filled, status, ts_ms "
            "FROM orders WHERE symbol = ? AND status != 'closed' ORDER BY ts_ms ASC",
            (symbol,),
        )
        rows = cur.fetchall() or []
        # If sqlite3.Row, convert to dict
        return [dict(r) if hasattr(r, "keys") else {
            "id": r[0], "broker_order_id": r[1], "client_order_id": r[2], "symbol": r[3], "side": r[4],
            "amount": r[5], "filled": r[6], "status": r[7], "ts_ms": r[8]
        } for r in rows]

    def mark_closed(self, broker_order_id: str, filled: str) -> None:
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE orders SET status='closed', filled=? WHERE broker_order_id=?",
            (str(filled), broker_order_id),
        )
        self.conn.commit()
