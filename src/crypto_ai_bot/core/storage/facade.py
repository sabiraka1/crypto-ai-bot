from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any, Iterable
from crypto_ai_bot.core.brokers.base import OrderDTO


# --- Контракты репозиториев (без реализаций) ---
class TradesRepository(Protocol):
    def create_pending_order(self, order: OrderDTO) -> None: ...
    def record_exchange_update(self, order: OrderDTO) -> None: ...
    def get_realized_pnl(self, *, symbol: str | None = None) -> float: ...


class PositionsRepository(Protocol):
    def get_open_positions(self) -> Iterable[Any]: ...
    def has_long(self, symbol: str) -> bool: ...
    def recompute_from_trades(self) -> None: ...


class MarketDataRepository(Protocol):
    def save_snapshot(self, symbol: str, ohlcv: list[list[float]]) -> None: ...
    def get_latest_ohlcv(self, symbol: str, *, limit: int = 100) -> list[list[float]]: ...


class AuditRepository(Protocol):
    def log_event(self, event: str, details: dict) -> None: ...
    def get_recent_events(self, *, limit: int = 100) -> list[dict]: ...


class IdempotencyRepository(Protocol):
    def check_and_store(self, key: str, ttl: int) -> bool: ...
    def commit(self, key: str) -> None: ...
    def cleanup_expired(self) -> int: ...


# --- Фасад хранилища ---
@dataclass(slots=True)
class Storage:
    trades: TradesRepository
    positions: PositionsRepository
    market_data: MarketDataRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository

    # Фабрика из подключения БД — импортируем реализацию динамически (не ломает фундамент)
    @classmethod
    def from_connection(cls, db_conn: object) -> "Storage":
        """Создаёт репозитории из подключения. Требует реальных реализаций в `core/storage/repositories/`.
        Реализации могут быть добавлены позже без изменения интерфейсов.
        """
        from importlib import import_module
        trades_mod = import_module("crypto_ai_bot.core.storage.repositories.trades")
        positions_mod = import_module("crypto_ai_bot.core.storage.repositories.positions")
        market_mod = import_module("crypto_ai_bot.core.storage.repositories.market_data")
        audit_mod = import_module("crypto_ai_bot.core.storage.repositories.audit")
        idem_mod = import_module("crypto_ai_bot.core.storage.repositories.idempotency")
        return cls(
            trades=trades_mod.TradesRepositoryImpl(db_conn),
            positions=positions_mod.PositionsRepositoryImpl(db_conn),
            market_data=market_mod.MarketDataRepositoryImpl(db_conn),
            audit=audit_mod.AuditRepositoryImpl(db_conn),
            idempotency=idem_mod.IdempotencyRepositoryImpl(db_conn),
        )