from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

@dataclass
class TradesRepository:
    conn: Any  # sqlite3.Connection with row_factory=sqlite3.Row

    def __post_init__(self) -> None:
        try:
            self.ensure_schema()
        except Exception:
            pass

    def ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_order_id TEXT,
    client_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    amount TEXT NOT NULL,
    filled TEXT NOT NULL,
    price TEXT NOT NULL,
    cost TEXT NOT NULL,
    fee_quote TEXT NOT NULL,
    ts_ms INTEGER NOT NULL
)""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts_ms)")
        self.conn.commit()

    def add_from_order(self, order: Any) -> None:
        """Insert order fields expected in tests into trades table."""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO trades (broker_order_id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                getattr(order, "id", None),
                getattr(order, "client_order_id", None),
                getattr(order, "symbol", None),
                getattr(order, "side", None),
                str(getattr(order, "amount", Decimal("0"))),
                str(getattr(order, "filled", getattr(order, "amount", Decimal("0")))),
                str(getattr(order, "price", Decimal("0"))),
                str(getattr(order, "cost", Decimal("0"))),
                str(getattr(order, "fee_quote", Decimal("0"))),
                int(getattr(order, "ts_ms", 0)),
            ),
        )
        self.conn.commit()
