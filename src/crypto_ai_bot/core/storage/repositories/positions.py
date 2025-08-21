from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
@dataclass(frozen=True)
class Position:
    symbol: str
    base_qty: Decimal  # суммарное количество базовой валюты (BUY - SELL)
class PositionsRepository:
    """Позиции считаются на лету из таблицы trades (по закрытым сделкам)."""
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
    def get_base_qty(self, symbol: str) -> Decimal:
        cur = self._c.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN side='buy' THEN amount ELSE -amount END), 0)
            FROM trades WHERE symbol = ? AND status = 'closed'
            """,
            (symbol,),
        )
        val = cur.fetchone()[0]
        return Decimal(str(val or 0))
    def get_position(self, symbol: str) -> Position:
        return Position(symbol=symbol, base_qty=self.get_base_qty(symbol))
    def has_open_position(self, symbol: str) -> bool:
        return self.get_base_qty(symbol) != Decimal("0")