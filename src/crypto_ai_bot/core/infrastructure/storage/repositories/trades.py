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
        # ensure broker_order_id exists even if table was created earlier without it
        cur.execute("PRAGMA table_info(trades)")
        cols = [r[1] for r in cur.fetchall()]
        if "broker_order_id" not in cols:
            cur.execute("ALTER TABLE trades ADD COLUMN broker_order_id TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts_ms)")
        self.conn.commit()

    def add_from_order(self, order: Any) -> None:
        self.ensure_schema()  # make sure latest columns exist
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


from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.pnl import fifo_pnl

    def _row_to_dict(self, row: Any) -> dict:
        # Convert sqlite3.Row to plain dict with expected keys
        return {
            "id": row["id"] if "id" in row.keys() else None,
            "client_order_id": row["client_order_id"] if "client_order_id" in row.keys() else None,
            "symbol": row["symbol"],
            "side": row["side"],
            "amount": row["amount"],
            "filled": row["filled"],
            "price": row["price"],
            "cost": row["cost"],
            "fee_quote": row["fee_quote"],
            "ts_ms": row["ts_ms"],
        }

    def _start_of_today_ms(self) -> int:
        dt = datetime.now(timezone.utc).astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return int(dt.timestamp() * 1000)

    def list_today(self, symbol: str) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms "
            "FROM trades WHERE symbol = ? AND ts_ms >= ? ORDER BY ts_ms ASC",
            (symbol, self._start_of_today_ms(),),
        )
        rows = cur.fetchall() or []
        return [self._row_to_dict(r) for r in rows]

    def last_trades(self, symbol: str, limit: int) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms "
            "FROM trades WHERE symbol = ? ORDER BY ts_ms DESC LIMIT ?",
            (symbol, int(limit),),
        )
        rows = cur.fetchall() or []
        rows = list(reversed(rows))  # return chronological
        return [self._row_to_dict(r) for r in rows]

    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        # Minutes window measured backward from now
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        window_ms = now_ms - int(minutes * 60 * 1000)
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(1) FROM trades WHERE symbol = ? AND ts_ms >= ?", (symbol, window_ms))
        row = cur.fetchone()
        return int(row[0] if row else 0)

    def count_orders_today(self, symbol: str) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(1) FROM trades WHERE symbol = ? AND ts_ms >= ?", (symbol, self._start_of_today_ms()))
        row = cur.fetchone()
        return int(row[0] if row else 0)

    def daily_pnl_quote(self, symbol: str) -> Decimal:
        trades = self.list_today(symbol)
        res = fifo_pnl(trades)
        return dec(str(res.realized_quote))

    def pnl_today_quote(self, symbol: str) -> Decimal:
        # Alias for daily_pnl_quote (compatibility)
        return self.daily_pnl_quote(symbol)
