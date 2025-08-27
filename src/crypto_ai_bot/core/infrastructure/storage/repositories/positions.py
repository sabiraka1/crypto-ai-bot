from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class Position:
    symbol: str
    base_qty: Decimal
    # Расширенные поля — пока вычисляемые/в памяти, без требований к схеме БД.
    avg_entry_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    opened_at: int = 0
    updated_at: int = 0


class PositionsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_position(self, symbol: str) -> Position:
        cur = self._c.execute("SELECT base_qty FROM positions WHERE symbol=?", (symbol,))
        row = cur.fetchone()
        if not row:
            return Position(symbol, Decimal("0"))
        return Position(symbol, Decimal(str(row[0])))

    # совместимость со старым кодом
    def get_base_qty(self, symbol: str) -> Decimal:
        return self.get_position(symbol).base_qty

    def set_base_qty(self, symbol: str, base_qty: Decimal) -> None:
        self._c.execute(
            """INSERT INTO positions(symbol, base_qty) VALUES(?, ?)
               ON CONFLICT(symbol) DO UPDATE SET base_qty=excluded.base_qty""",
            (symbol, str(base_qty)),
        )

    # лёгкая интеграция для reconcile: обновить позицию на основе сделки (минимум — базовое количество)
    def update_from_trade(self, trade: dict) -> Position:
        sym = str(trade["symbol"])
        side = str(trade["side"]).lower()
        amount = Decimal(str(trade["amount"]))
        pos = self.get_position(sym)

        if side == "buy":
            pos.base_qty = pos.base_qty + amount
        else:
            pos.base_qty = max(Decimal("0"), pos.base_qty - amount)

        self.set_base_qty(sym, pos.base_qty)
        return pos


# --- compatibility aliases expected by storage.facade ---
try:
    PositionsRepo  # if already defined under this exact name
except NameError:
    try:
        PositionsRepo = PositionsRepository  # type: ignore[name-defined]
    except NameError:
        try:
            PositionsRepo = PositionRepo  # type: ignore[name-defined]
        except NameError:
            # no alias available; leave as-is to surface a clear error
            pass