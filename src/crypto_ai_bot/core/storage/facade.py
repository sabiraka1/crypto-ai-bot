## `core/storage/facade.py`
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from .repositories.trades import TradesRepository
from .repositories.positions import PositionsRepository
from .repositories.market_data import MarketDataRepository
from .repositories.audit import AuditRepository
from .repositories.idempotency import IdempotencyRepository
@dataclass(frozen=True)
class Storage:
    """Единая точка доступа к репозиториям. Логики внутри нет."""
    conn: sqlite3.Connection
    trades: TradesRepository
    positions: PositionsRepository
    market_data: MarketDataRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository
    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "Storage":
        return cls(
            conn=conn,
            trades=TradesRepository(conn),
            positions=PositionsRepository(conn),
            market_data=MarketDataRepository(conn),
            audit=AuditRepository(conn),
            idempotency=IdempotencyRepository(conn),
        )