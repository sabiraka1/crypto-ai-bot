
# -*- coding: utf-8 -*-
"""
core.positions.manager
Lightweight position manager that uses repositories.
Does NOT place real orders вЂ” it's a coordination layer.
Real order execution should be in core.bot using broker adapter.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from crypto_ai_bot.core.storage.repositories.positions import Position, PositionRepository
from crypto_ai_bot.core.storage.repositories.trades import Trade, TradeRepository


class PositionManager:
    def __init__(self, positions: PositionRepository, trades: TradeRepository):
        self.positions = positions
        self.trades = trades

    def open(self, symbol: str, qty: float, price: float) -> str:
        pos_id = str(uuid.uuid4())
        now = int(time.time()*1000)
        p = Position(id=pos_id, symbol=symbol, qty=qty, avg_price=price, status="open", opened_ts=now, closed_ts=None, pnl=0.0)
        self.positions.open(p)
        t = Trade(id=str(uuid.uuid4()), pos_id=pos_id, symbol=symbol, side="buy", qty=qty, price=price, fee=0.0, ts=now)
        self.trades.add(t)
        return pos_id

    def partial_close(self, pos_id: str, fraction: float, price: float) -> None:
        pos = self.positions.get(pos_id)
        if not pos or pos.status != "open":
            return
        fraction = max(0.0, min(1.0, float(fraction)))
        close_qty = pos.qty * fraction
        if close_qty <= 0.0:
            return
        new_qty = pos.qty - close_qty
        now = int(time.time()*1000)
        # record trade
        self.trades.add(Trade(id=str(uuid.uuid4()), pos_id=pos_id, symbol=pos.symbol, side="sell", qty=close_qty, price=price, fee=0.0, ts=now))
        if new_qty <= 1e-12:
            # fully closed
            pnl = (price - pos.avg_price) * pos.qty
            self.positions.close(pos_id=pos_id, closed_ts=now, pnl=pnl)
        else:
            # adjust position
            pnl_piece = (price - pos.avg_price) * close_qty
            pos.qty = new_qty
            pos.pnl += pnl_piece
            self.positions.update(pos)

    def close(self, pos_id: str, price: float) -> None:
        pos = self.positions.get(pos_id)
        if not pos or pos.status != "open":
            return
        now = int(time.time()*1000)
        pnl = (price - pos.avg_price) * pos.qty
        # record trade
        self.trades.add(Trade(id=str(uuid.uuid4()), pos_id=pos_id, symbol=pos.symbol, side="sell", qty=pos.qty, price=price, fee=0.0, ts=now))
        self.positions.close(pos_id=pos_id, closed_ts=now, pnl=pnl)

