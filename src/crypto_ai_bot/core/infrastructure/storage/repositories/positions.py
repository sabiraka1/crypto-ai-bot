from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.time import now_ms


@dataclass
class Position:
    symbol: str
    base_qty: Decimal
    avg_entry_price: Decimal = dec("0")
    realized_pnl: Decimal = dec("0")
    unrealized_pnl: Decimal = dec("0")
    opened_at: int = 0
    updated_at: int = 0
    last_trade_ts_ms: int = 0


class PositionsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_position(self, symbol: str) -> Position:
        cur = self._c.execute(
            """
            SELECT base_qty,
                   COALESCE(avg_entry_price, 0),
                   COALESCE(realized_pnl, 0),
                   COALESCE(unrealized_pnl, 0),
                   COALESCE(opened_at, 0),
                   COALESCE(updated_at, 0),
                   COALESCE(last_trade_ts_ms, 0)
            FROM positions
            WHERE symbol=?
            """,
            (symbol,),
        )
        row = cur.fetchone()
        if not row:
            return Position(symbol=symbol, base_qty=dec("0"))
        return Position(
            symbol=symbol,
            base_qty=dec(str(row[0])),
            avg_entry_price=dec(str(row[1])),
            realized_pnl=dec(str(row[2])),
            unrealized_pnl=dec(str(row[3])),
            opened_at=int(row[4]),
            updated_at=int(row[5]),
            last_trade_ts_ms=int(row[6]),
        )

    def get_base_qty(self, symbol: str) -> Decimal:
        return self.get_position(symbol).base_qty

    def set_base_qty(self, symbol: str, base_qty: Decimal) -> None:
        self._c.execute(
            """
            INSERT INTO positions(symbol, base_qty, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                base_qty=excluded.base_qty,
                updated_at=excluded.updated_at
            """,
            (symbol, str(base_qty), now_ms()),
        )
        self._c.commit()  # ← добавлено

    def set_last_trade_ts(self, symbol: str, ts_ms: Optional[int] = None) -> None:
        ts = int(ts_ms or now_ms())
        self._c.execute(
            """
            INSERT INTO positions(symbol, last_trade_ts_ms, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                last_trade_ts_ms=excluded.last_trade_ts_ms,
                updated_at=excluded.updated_at
            """,
            (symbol, ts, ts),
        )
        self._c.commit()  # ← добавлено

    def get_last_trade_ts(self, symbol: str) -> int:
        cur = self._c.execute("SELECT COALESCE(last_trade_ts_ms, 0) FROM positions WHERE symbol=?", (symbol,))
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def is_cooldown_active(self, symbol: str, cooldown_sec: int, *, now_ts_ms: Optional[int] = None) -> bool:
        if cooldown_sec <= 0:
            return False
        last = self.get_last_trade_ts(symbol)
        if last <= 0:
            return False
        now_local = int(now_ts_ms or now_ms())
        return (now_local - last) < int(cooldown_sec * 1000)

    def update_from_trade(self, trade: dict) -> Position:
        sym = str(trade["symbol"])
        side = str(trade["side"]).lower()
        amount = dec(str(trade["amount"]))
        pos = self.get_position(sym)
        if side == "buy":
            pos.base_qty = pos.base_qty + amount
        else:
            pos.base_qty = max(dec("0"), pos.base_qty - amount)

        self.set_base_qty(sym, pos.base_qty)
        ts_ms = int(trade.get("ts_ms", 0)) if isinstance(trade, dict) else 0
        if ts_ms > 0:
            self.set_last_trade_ts(sym, ts_ms)
        return pos


PositionsRepo = PositionsRepository
