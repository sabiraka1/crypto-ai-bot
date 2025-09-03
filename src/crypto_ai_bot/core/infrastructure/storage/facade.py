# src/crypto_ai_bot/core/infrastructure/storage/facade.py
from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from .repositories.audit import AuditRepo as _AuditRepository
from .repositories.idempotency import IdempotencyRepository as _IdempotencyRepository
from .repositories.market_data import MarketDataRepository as _MarketDataRepository
from .repositories.orders import OrdersRepository as _OrdersRepository
from .repositories.positions import PositionsRepository as _PositionsRepository
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

    # С‡РµСЃС‚РЅС‹Р№ health-ping РґР»СЏ /health
    async def ping(self) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        return True
