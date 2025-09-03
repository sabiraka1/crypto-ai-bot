from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast


def _get(obj: Any, attr: str, key: str | None = None, default: Any = None) -> Any:
    """Ğ”Ğ¾ÑÑ‚Ğ°Ñ‘Ğ¼ Ğ·Ğ½Ğ°Ñ‡ĞµĞ½Ğ¸Ğµ Ğ¸Ğ· Ğ¾Ğ±ÑŠĞµĞºÑ‚Ğ° Ğ˜Ğ›Ğ˜ dict (ÑƒĞ½Ğ¸Ğ²ĞµÑ€ÑĞ°Ğ»ÑŒĞ½Ğ¾ Ğ´Ğ»Ñ CCXT-Ğ¾Ñ‚Ğ²ĞµÑ‚Ğ¾Ğ²)."""
    if hasattr(obj, attr):
        try:
            return getattr(obj, attr)
        except Exception:
            pass
    if key and isinstance(obj, dict):
        try:
            return obj.get(key, default)
        except Exception:
            pass
    return default


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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
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
            )
            """
        )
        # ensure broker_order_id exists even if table was created earlier without it
        cur.execute("PRAGMA table_info(trades)")
        cols = [r[1] for r in cur.fetchall()]
        if "broker_order_id" not in cols:
            cur.execute("ALTER TABLE trades ADD COLUMN broker_order_id TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades(symbol, ts_ms)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_side_ts ON trades(symbol, side, ts_ms)")
        self.conn.commit()

    # ---------- INSERTS / LISTS ----------

    def add_from_order(self, order: Any) -> None:
        """Ğ¡Ğ¾Ñ…Ñ€Ğ°Ğ½ÑĞµĞ¼ Ğ¸ÑĞ¿Ğ¾Ğ»Ğ½ĞµĞ½Ğ½Ñ‹Ğ¹ Ğ¾Ñ€Ğ´ĞµÑ€ Ğ² trades. ĞŸĞ¾Ğ´Ğ´ĞµÑ€Ğ¶Ğ¸Ğ²Ğ°ĞµÑ‚ Ğ¸ Ğ¾Ğ±ÑŠĞµĞºÑ‚Ñ‹, Ğ¸ dict-Ğ¾Ñ‚Ğ²ĞµÑ‚ CCXT."""
        self.ensure_schema()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO trades (broker_order_id, client_order_id, symbol, side, amount, filled, price, cost, fee_quote, ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _get(order, "id", "id"),
                _get(order, "client_order_id", "clientOrderId"),
                _get(order, "symbol", "symbol"),
                _get(order, "side", "side"),
                str(_get(order, "amount", "amount", Decimal("0"))),
                str(_get(order, "filled", "filled", _get(order, "amount", "amount", Decimal("0")))),
                str(_get(order, "price", "price", Decimal("0"))),
                str(_get(order, "cost", "cost", Decimal("0"))),
                # fee Ğ¼Ğ¾Ğ¶ĞµÑ‚ Ğ±Ñ‹Ñ‚ÑŒ dict: {"cost": ..., "currency": "..."}
                str(
                    _get(order, "fee_quote", "fee_quote")
                    if _get(order, "fee_quote", "fee_quote") is not None
                    else (
                        (_get(order, "fee", "fee") or {}).get("cost", "0")
                        if isinstance(_get(order, "fee", "fee"), dict)
                        else "0"
                    )
                ),
                int(_get(order, "ts_ms", "timestamp", 0)),
            ),
        )
        self.conn.commit()

    def list_today(self, symbol: str) -> list[Any]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM trades
            WHERE symbol = ?
              AND DATE(ts_ms/1000, 'unixepoch') = DATE('now')
            ORDER BY ts_ms DESC
            """,
            (symbol,),
        )
        return cast(list[Any], cur.fetchall())

    def last_trades(self, symbol: str, limit: int = 50) -> list[Any]:
        """ĞŸĞ¾ÑĞ»ĞµĞ´Ğ½Ğ¸Ğµ N ÑĞ´ĞµĞ»Ğ¾Ğº Ğ¿Ğ¾ ÑĞ¸Ğ¼Ğ²Ğ¾Ğ»Ñƒ (DESC)."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM trades
            WHERE symbol = ?
            ORDER BY ts_ms DESC
            LIMIT ?
            """,
            (symbol, int(limit)),
        )
        return cast(list[Any], cur.fetchall())

    def daily_turnover_quote(self, symbol: str) -> Decimal:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(SUM(CAST(cost AS REAL)), 0) as turnover
            FROM trades
            WHERE symbol = ?
              AND DATE(ts_ms/1000, 'unixepoch') = DATE('now')
            """,
            (symbol,),
        )
        result = cur.fetchone()
        return Decimal(str(result[0] if result else 0))

    def count_orders_last_minutes(self, symbol: str, minutes: int) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) as cnt
            FROM trades
            WHERE symbol = ?
              AND ts_ms > (CAST(STRFTIME('%s', 'now') AS INTEGER) * 1000 - ? * 60 * 1000)
            """,
            (symbol, minutes),
        )
        result = cur.fetchone()
        return int(result[0] if result else 0)

    def count_orders_today(self, symbol: str) -> int:
        """Ğ¡ĞºĞ¾Ğ»ÑŒĞºĞ¾ Ğ¸ÑĞ¿Ğ¾Ğ»Ğ½ĞµĞ½Ğ¸Ğ¹ Ğ¿Ğ¾ ÑĞ¸Ğ¼Ğ²Ğ¾Ğ»Ñƒ Ğ·Ğ° ÑĞµĞ³Ğ¾Ğ´Ğ½Ñ (UTC)."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM trades
            WHERE symbol = ?
              AND DATE(ts_ms/1000, 'unixepoch') = DATE('now')
            """,
            (symbol,),
        )
        row = cur.fetchone()
        return int(row[0] if row else 0)

    # ---------- FIFO PnL (Ñ ÑƒÑ‡Ñ‘Ñ‚Ğ¾Ğ¼ fee_quote) ----------

    def _iter_all_asc(self, symbol: str) -> list[Any]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT side, amount, filled, price, cost, fee_quote, ts_ms
            FROM trades
            WHERE symbol = ?
            ORDER BY ts_ms ASC
            """,
            (symbol,),
        )
        return cast(list[Any], cur.fetchall())

    @staticmethod
    def _to_dec(x: Any) -> Decimal:
        return Decimal(str(x if x is not None else "0"))

    def pnl_today_quote(self, symbol: str) -> Decimal:
        """Ğ ĞµĞ°Ğ»Ğ¸Ğ·Ğ¾Ğ²Ğ°Ğ½Ğ½Ñ‹Ğ¹ PnL Ğ·Ğ° ÑĞµĞ³Ğ¾Ğ´Ğ½Ñ (UTC, quote), FIFO, Ñ ÑƒÑ‡Ñ‘Ñ‚Ğ¾Ğ¼ fee_quote."""
        return self._pnl_today_fifo_quote(symbol)

    # ĞĞ»Ğ¸Ğ°Ñ Ğ´Ğ»Ñ Ñ‡Ğ¸Ñ‚Ğ°ĞµĞ¼Ğ¾ÑÑ‚Ğ¸ ÑĞ½Ğ°Ñ€ÑƒĞ¶Ğ¸:
    def daily_pnl_quote(self, symbol: str) -> Decimal:
        return self.pnl_today_quote(symbol)

    def _pnl_today_fifo_quote(self, symbol: str) -> Decimal:
        rows = self._iter_all_asc(symbol)

        # FIFO-Ğ¾Ñ‡ĞµÑ€ĞµĞ´ÑŒ Ğ¿Ğ¾ĞºÑƒĞ¿Ğ¾Ğº: ÑĞ»ĞµĞ¼ĞµĞ½Ñ‚Ñ‹ (qty_left, unit_cost_quote)
        # unit_cost_quote = (cost + fee_quote) / filled
        buy_lots: list[tuple[Decimal, Decimal]] = []

        pnl_today = Decimal("0")

        import datetime as _dt

        today_utc = _dt.datetime.utcnow().date()

        for r in rows:
            side = (r["side"] or "").lower()
            filled = self._to_dec(r["filled"] or r["amount"])
            price = self._to_dec(r["price"])
            cost = self._to_dec(r["cost"])
            fee_q = self._to_dec(r["fee_quote"])
            ts_ms = int(r["ts_ms"] or 0)
            ts_day = _dt.datetime.utcfromtimestamp(ts_ms / 1000).date()

            if filled <= 0:
                continue

            if side == "buy":
                unit_cost = (cost + fee_q) / filled if filled > 0 else Decimal("0")
                buy_lots.append((filled, unit_cost))
                continue

            if side == "sell":
                qty_to_consume = filled
                unit_sell = price  # Ğ²Ñ‹Ñ€ÑƒÑ‡ĞºĞ° Ğ´Ğ¾ ĞºĞ¾Ğ¼Ğ¸ÑÑĞ¸Ğ¸
                realized = Decimal("0")

                i = 0
                while qty_to_consume > 0 and i < len(buy_lots):
                    lot_qty, lot_uc = buy_lots[i]
                    take = min(lot_qty, qty_to_consume)
                    realized += take * (unit_sell - lot_uc)
                    new_qty = lot_qty - take
                    qty_to_consume -= take
                    if new_qty > 0:
                        buy_lots[i] = (new_qty, lot_uc)
                        i += 1
                    else:
                        buy_lots.pop(i)

                # ĞºĞ¾Ğ¼Ğ¸ÑÑĞ¸Ñ Ğ¿Ñ€Ğ¾Ğ´Ğ°Ğ¶Ğ¸ Ğ¾Ñ‚Ğ½Ğ¾ÑĞ¸Ñ‚ÑÑ Ğº Ğ¿Ñ€Ğ¾Ğ´Ğ°Ğ¶Ğµ
                if ts_day == today_utc:
                    pnl_today += realized - fee_q

        return pnl_today
