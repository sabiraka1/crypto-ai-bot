# src/crypto_ai_bot/core/infrastructure/storage/facade.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .repositories.audit import AuditRepo as _AuditRepository
from .repositories.idempotency import IdempotencyRepository as _IdempotencyRepository
from .repositories.market_data import MarketDataRepo as _MarketDataRepository
from .repositories.positions import PositionsRepository as _PositionsRepository
from .repositories.orders import OrdersRepository as _OrdersRepository

# Импорты ровно под реальные классы в репозиториях
from .repositories.trades import TradesRepository as _TradesRepository


@dataclass
class Storage:
    conn: sqlite3.Connection
    trades: _TradesRepository
    positions: _PositionsRepository
    orders: _OrdersRepository
    idempotency: _IdempotencyRepository
    audit: _AuditRepository
    market_data: _MarketDataRepository

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> Storage:
        return cls(
            conn=conn,
            trades=_TradesRepository(conn),
            positions=_PositionsRepository(conn),
            idempotency=_IdempotencyRepository(conn),
            audit=_AuditRepository(conn),
            market_data=_MarketDataRepository(conn),
            orders=_OrdersRepository(conn),
        )
