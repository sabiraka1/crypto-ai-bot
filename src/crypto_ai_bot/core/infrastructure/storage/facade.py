from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .repositories.trades import TradesRepository
from .repositories.positions import PositionsRepository
from .repositories.idempotency import IdempotencyRepository
from .repositories.audit import AuditRepository
from .repositories.market_data import MarketDataRepository


@dataclass
class Storage:
    conn: sqlite3.Connection
    trades: TradesRepository
    positions: PositionsRepository
    idempotency: IdempotencyRepository
    audit: AuditRepository
    market_data: MarketDataRepository

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "Storage":
        return cls(
            conn=conn,
            trades=TradesRepository(conn),
            positions=PositionsRepository(conn),
            idempotency=IdempotencyRepository(conn),
            audit=AuditRepository(conn),
            market_data=MarketDataRepository(conn),
        )
