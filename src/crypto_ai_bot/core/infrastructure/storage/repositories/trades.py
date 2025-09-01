from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass
class TradesRepository:
    conn: Any  # sqlite3.Connection with row_factory=sqlite3.Row

    def __post_init__(self) -> None:
        # ensure schema exists (for in-memory DB or fresh file DB)
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

    # ... остальные методы (add_from_order, pnl_today_quote и т.д.) остаются без изменений ...
