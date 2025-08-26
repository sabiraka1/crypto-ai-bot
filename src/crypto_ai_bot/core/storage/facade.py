from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .repositories.audit import AuditRepository
from .repositories.idempotency import IdempotencyRepository
from .repositories.market_data import MarketDataRepository
from .repositories.positions import PositionsRepository
from .repositories.trades import TradesRepository


@dataclass
class Storage:
    conn: sqlite3.Connection
    trades: TradesRepository          # ✅ добавлено
    audit: AuditRepository
    idempotency: IdempotencyRepository
    positions: PositionsRepository
    market_data: MarketDataRepository

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "Storage":
        return cls(
            conn=conn,
            trades=TradesRepository(conn),          # ✅ добавлено
            audit=AuditRepository(conn),
            idempotency=IdempotencyRepository(conn),
            positions=PositionsRepository(conn),
            market_data=MarketDataRepository(conn),
        )
