
# -*- coding: utf-8 -*-
"""
core.storage.repositories.positions
Interface for position persistence.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Position:
    id: str
    symbol: str
    qty: float
    avg_price: float
    status: str  # 'open'|'closed'
    opened_ts: int
    closed_ts: Optional[int] = None
    pnl: float = 0.0

class PositionRepository:
    def open(self, p: Position) -> None: ...
    def update(self, p: Position) -> None: ...
    def close(self, pos_id: str, closed_ts: int, pnl: float) -> None: ...
    def get(self, pos_id: str) -> Optional[Position]: ...
    def list_open(self, symbol: Optional[str] = None) -> List[Position]: ...
    def recent(self, limit: int = 50) -> List[Position]: ...










