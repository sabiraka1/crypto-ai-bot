from __future__ import annotations

from dataclasses import dataclass
import sqlite3

# Пытаемся использовать твои репозитории, если они есть…
try:
    from .repositories.audit import AuditRepo as _AuditRepository  # type: ignore
    from .repositories.idempotency import IdempotencyRepository as _IdempotencyRepository  # type: ignore
    from .repositories.market_data import MarketDataRepository as _MarketDataRepository  # type: ignore
    from .repositories.orders import OrdersRepository as _OrdersRepository  # type: ignore
    from .repositories.positions import PositionsRepository as _PositionsRepository  # type: ignore
    from .repositories.trades import TradesRepository as _TradesRepository  # type: ignore
except Exception:  # pragma: no cover
    # …иначе — минимальные совместимые заглушки/альтернативы
    from crypto_ai_bot.core.infrastructure.idempotency import (
        IdempotencyRepository as _IdempotencyRepository,  # type: ignore
    )

    class _StubRepo:
        def __init__(self, _conn: sqlite3.Connection) -> None: ...

    _AuditRepository = _StubRepo  # type: ignore
    _MarketDataRepository = _StubRepo  # type: ignore
    _OrdersRepository = _StubRepo  # type: ignore
    _PositionsRepository = _StubRepo  # type: ignore
    _TradesRepository = _StubRepo  # type: ignore


@dataclass
class StorageFacade:
    """
    Единая точка доступа к БД/репозиториям.
    Совместима с прежним кодом; добавлены удобные методы ping()/close().
    """

    conn: sqlite3.Connection
    trades: _TradesRepository
    positions: _PositionsRepository
    orders: _OrdersRepository
    idempotency: _IdempotencyRepository
    audit: _AuditRepository
    market_data: _MarketDataRepository

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> StorageFacade:
        return cls(
            conn=conn,
            trades=_TradesRepository(conn),  # type: ignore[call-arg]
            positions=_PositionsRepository(conn),  # type: ignore[call-arg]
            idempotency=_IdempotencyRepository(conn),  # type: ignore[call-arg]
            audit=_AuditRepository(conn),  # type: ignore[call-arg]
            market_data=_MarketDataRepository(conn),  # type: ignore[call-arg]
            orders=_OrdersRepository(conn),  # type: ignore[call-arg]
        )

    # честный health-ping для /health
    async def ping(self) -> bool:
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT 1;")
            cur.fetchone()
            return True
        finally:
            cur.close()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# Обратная совместимость с твоим именованием класса (если где-то используется `Storage`)
Storage = StorageFacade
