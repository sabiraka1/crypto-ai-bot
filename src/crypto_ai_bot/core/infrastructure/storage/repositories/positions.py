from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
from datetime import datetime, timezone

from crypto_ai_bot.utils.decimal import dec


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


@dataclass
class Position:
    symbol: str
    base_qty: Decimal
    avg_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    updated_ts_ms: int


@dataclass
class PositionsRepository:
    conn: Any  # sqlite3.Connection с row_factory=sqlite3.Row

    def get_position(self, symbol: str) -> Position:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms
            FROM positions
            WHERE symbol = ?
            """,
            (symbol,),
        )
        r = cur.fetchone()
        if not r:
            return Position(
                symbol=symbol,
                base_qty=dec("0"),
                avg_entry_price=dec("0"),
                realized_pnl=dec("0"),
                unrealized_pnl=dec("0"),
                updated_ts_ms=0,
            )
        return Position(
            symbol=r["symbol"],
            base_qty=dec(str(r["base_qty"] or "0")),
            avg_entry_price=dec(str(r["avg_entry_price"] or "0")),
            realized_pnl=dec(str(r["realized_pnl"] or "0")),
            unrealized_pnl=dec(str(r["unrealized_pnl"] or "0")),
            updated_ts_ms=int(r["updated_ts_ms"] or 0),
        )

    def set_base_qty(self, symbol: str, value: Decimal) -> None:
        cur = self.conn.cursor()
        ts = _now_ms()
        cur.execute(
            """
            INSERT INTO positions (symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms)
            VALUES (?, ?, COALESCE((SELECT avg_entry_price FROM positions WHERE symbol=?), '0'),
                    COALESCE((SELECT realized_pnl FROM positions WHERE symbol=?), '0'),
                    COALESCE((SELECT unrealized_pnl FROM positions WHERE symbol=?), '0'),
                    ?)
            ON CONFLICT(symbol) DO UPDATE SET
                base_qty = excluded.base_qty,
                updated_ts_ms = excluded.updated_ts_ms
            """,
            (symbol, str(value), symbol, symbol, symbol, ts),
        )
        self.conn.commit()

    def apply_trade(self, *, symbol: str, side: str, base_amount: Decimal,
                    price: Decimal, fee_quote: Decimal = dec("0"),
                    last_price: Optional[Decimal] = None) -> None:
        side = (side or "").lower().strip()
        if side not in ("buy", "sell"):
            return

        pos = self.get_position(symbol)
        base0 = pos.base_qty
        avg0 = pos.avg_entry_price
        realized0 = pos.realized_pnl

        if side == "buy":
            if base_amount <= 0:
                return
            new_base = base0 + base_amount
            new_avg = ((avg0 * base0) + (price * base_amount)) / new_base if new_base > 0 else dec("0")
            new_realized = realized0 - (fee_quote if fee_quote else dec("0"))
        else:
            if base_amount <= 0:
                return
            matched = base_amount if base_amount <= base0 else base0
            pnl = (price - avg0) * matched
            new_realized = realized0 + pnl - (fee_quote if fee_quote else dec("0"))
            new_base = base0 - base_amount
            new_avg = avg0 if new_base > 0 else dec("0")

        ref_price = (last_price if last_price is not None else price) or dec("0")
        if new_base > 0 and new_avg > 0 and ref_price > 0:
            new_unreal = (ref_price - new_avg) * new_base
        else:
            new_unreal = dec("0")

        cur = self.conn.cursor()
        ts = _now_ms()
        cur.execute(
            """
            INSERT INTO positions (symbol, base_qty, avg_entry_price, realized_pnl, unrealized_pnl, updated_ts_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                base_qty = excluded.base_qty,
                avg_entry_price = excluded.avg_entry_price,
                realized_pnl = excluded.realized_pnl,
                unrealized_pnl = excluded.unrealized_pnl,
                updated_ts_ms = excluded.updated_ts_ms
            """,
            (symbol, str(new_base), str(new_avg), str(new_realized), str(new_unreal), ts),
        )
        self.conn.commit()
