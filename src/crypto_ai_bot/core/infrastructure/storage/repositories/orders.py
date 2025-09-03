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

    # ---------- helpers ----------

    def _exists_by_broker_id(self, broker_order_id: str | None) -> bool:
        if not broker_order_id:
            return False
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM orders WHERE broker_order_id = ? LIMIT 1", (broker_order_id,))
        return cur.fetchone() is not None

    def _exists_by_client_id(self, client_order_id: str | None) -> bool:
        if not client_order_id:
            return False
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM orders WHERE client_order_id = ? LIMIT 1", (client_order_id,))
        return cur.fetchone() is not None

    # ---------- public API ----------

    def upsert_open(self, order: Any) -> None:
        """Ğ’ÑÑ‚Ğ°Ğ²Ğ»ÑĞµÑ‚ Ğ¾Ñ‚ĞºÑ€Ñ‹Ñ‚Ñ‹Ğ¹ Ğ¾Ñ€Ğ´ĞµÑ€, ĞµÑĞ»Ğ¸ Ñ‚Ğ°ĞºĞ¾Ğ³Ğ¾ ĞµÑ‰Ñ‘ Ğ½ĞµÑ‚ (Ğ¿Ğ¾ broker_id Ğ¸Ğ»Ğ¸ client_id)."""
        self.ensure_schema()
        broker_id = getattr(order, "id", None) or getattr(order, "order_id", None)
        client_id = getattr(order, "client_order_id", None)
        if self._exists_by_broker_id(broker_id) or self._exists_by_client_id(client_id):
            return
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO orders (broker_order_id, client_order_id, symbol, side, amount, filled, status, ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                broker_id,
                client_id,
                getattr(order, "symbol", None),
                getattr(order, "side", None),
                str(getattr(order, "amount", "0")),
                str(getattr(order, "filled", "0")),
                getattr(order, "status", "open") or "open",
                int(getattr(order, "ts_ms", 0)),
            ),
        )
        self.conn.commit()

    def list_open(self, symbol: str) -> list[dict[str, Any]]:
        """ĞÑ‚ĞºÑ€Ñ‹Ñ‚Ñ‹Ğµ (Ğ¸Ğ»Ğ¸ Ñ‡Ğ°ÑÑ‚Ğ¸Ñ‡Ğ½Ğ¾ Ğ¸ÑĞ¿Ğ¾Ğ»Ğ½ĞµĞ½Ğ½Ñ‹Ğµ) Ğ¾Ñ€Ğ´ĞµÑ€Ğ° Ğ¿Ğ¾ ÑĞ¸Ğ¼Ğ²Ğ¾Ğ»Ñƒ, ÑÑ‚Ğ°Ñ€Ñ‹Ğµ â†’ Ğ½Ğ¾Ğ²Ñ‹Ğµ."""
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, broker_order_id, client_order_id, symbol, side, amount, filled, status, ts_ms "
            "FROM orders WHERE symbol = ? AND status != 'closed' ORDER BY ts_ms ASC",
            (symbol,),
        )
        rows = cur.fetchall() or []
        result: list[dict[str, Any]] = []
        for r in rows:
            if hasattr(r, "keys"):
                result.append(dict(r))
            else:
                result.append(
                    {
                        "id": r[0],
                        "broker_order_id": r[1],
                        "client_order_id": r[2],
                        "symbol": r[3],
                        "side": r[4],
                        "amount": r[5],
                        "filled": r[6],
                        "status": r[7],
                        "ts_ms": r[8],
                    }
                )
        return result

    def update_progress(self, broker_order_id: str, filled: str) -> None:
        """ĞĞ±Ğ½Ğ¾Ğ²Ğ»ÑĞµÑ‚ filled, Ğ½Ğµ Ğ¼ĞµĞ½ÑÑ ÑÑ‚Ğ°Ñ‚ÑƒÑ."""
        if not broker_order_id:
            return
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE orders SET filled=? WHERE broker_order_id=? AND status!='closed'",
            (str(filled), broker_order_id),
        )
        self.conn.commit()

    def mark_closed(self, broker_order_id: str, filled: str) -> None:
        """ĞŸĞ¾Ğ¼ĞµÑ‡Ğ°ĞµÑ‚ Ğ¾Ñ€Ğ´ĞµÑ€ Ğ·Ğ°ĞºÑ€Ñ‹Ñ‚Ñ‹Ğ¼ Ğ¸ Ñ„Ğ¸ĞºÑĞ¸Ñ€ÑƒĞµÑ‚ Ñ„Ğ¸Ğ½Ğ°Ğ»ÑŒĞ½Ñ‹Ğ¹ filled."""
        if not broker_order_id:
            return
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE orders SET status='closed', filled=? WHERE broker_order_id=?",
            (str(filled), broker_order_id),
        )
        self.conn.commit()
