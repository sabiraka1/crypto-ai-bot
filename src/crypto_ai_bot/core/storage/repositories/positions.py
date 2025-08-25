from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Optional


class Position:
    def __init__(self, symbol: str, base_qty: Decimal) -> None:
        self.symbol = symbol
        self.base_qty = base_qty


class PositionsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn
        # Либо отдельная таблица, либо вычисляем из trades; тут — минимальная таблица
        self._c.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                base_qty TEXT NOT NULL
            )
            """
        )

    def get_position(self, symbol: str) -> Position:
        cur = self._c.execute("SELECT base_qty FROM positions WHERE symbol=?", (symbol,))
        row = cur.fetchone()
        if not row:
            return Position(symbol, Decimal("0"))
        return Position(symbol, Decimal(str(row[0])))

    def get_base_qty(self, symbol: str) -> Decimal:
        return self.get_position(symbol).base_qty

    def set_base_qty(self, symbol: str, base_qty: Decimal) -> None:
        self._c.execute(
            "INSERT INTO positions(symbol, base_qty) VALUES(?, ?)\n             ON CONFLICT(symbol) DO UPDATE SET base_qty=excluded.base_qty",
            (symbol, str(base_qty)),
        )