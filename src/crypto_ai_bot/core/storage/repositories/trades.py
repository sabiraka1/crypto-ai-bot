
# -*- coding: utf-8 -*-
"""
core.storage.repositories.trades
Interface for trade persistence.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Trade:
    id: str
    pos_id: Optional[str]
    symbol: str
    side: str   # 'buy'|'sell'
    qty: float
    price: float
    fee: float
    ts: int

class TradeRepository:
    def add(self, t: Trade) -> None: ...
    def list_for_position(self, pos_id: str) -> List[Trade]: ...
    def last(self, limit: int = 50) -> List[Trade]: ...






