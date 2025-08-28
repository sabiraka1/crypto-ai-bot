from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from crypto_ai_bot.utils.decimal import dec
from typing import Optional


@dataclass
class Position:
    symbol: str
    base_qty: Decimal
    # Расширенные поля — пока вычисляемые/в памяти, без требований к схеме БД.
    avg_entry_price: Decimal = dec("0")
    realized_pnl: Decimal = dec("0")
    unrealized_pnl: Decimal = dec("0")
    opened_at: int = 0
    updated_at: int = 0


class PositionsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def get_position(self, symbol: str) -> Position:
        cur = self._c.execute("SELECT base_qty FROM positions WHERE symbol=?", (symbol,))
        row = cur.fetchone()
        if not row:
            return Position(symbol, dec("0"))
        return Position(symbol, dec(str(row[0])))

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
        amount = dec(str(trade["amount"]))
        pos = self.get_position(sym)

        if side == "buy":
            pos.base_qty = pos.base_qty + amount
        else:
            pos.base_qty = max(dec("0"), pos.base_qty - amount)

        self.set_base_qty(sym, pos.base_qty)
        return pos


# --- compatibility alias ---
PositionsRepo = PositionsRepository