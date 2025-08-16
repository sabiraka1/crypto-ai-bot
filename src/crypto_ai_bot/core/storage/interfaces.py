# src/crypto_ai_bot/core/storage/interfaces.py
from __future__ import annotations
from contextlib import AbstractContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class UnitOfWork(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...


@runtime_checkable
class IdempotencyRepository(Protocol):
    """Единый контракт для идемпотентности:
    - claim/commit/release — базовые операции
    - purge_expired — обслуживание таблицы
    - check_and_store — «проверь и сохрани» первичные данные (для дублей вернуть оригинал)
    - get_original_order — вернуть сохранённый payload результата (например, order), если уже выполнялось
    """
    def claim(self, key: str, ttl_seconds: int) -> bool: ...
    def commit(self, key: str, payload_json: Optional[str] = None) -> None: ...
    def release(self, key: str) -> None: ...
    def purge_expired(self) -> int: ...
    def check_and_store(self, key: str, payload_json: str, ttl_seconds: int) -> tuple[bool, Optional[str]]: ...
    def get_original_order(self, key: str) -> Optional[str]: ...


@dataclass
class Trade:
    id: str
    symbol: str
    side: str
    amount: Decimal
    price: Decimal
    cost: Decimal
    fee_currency: str
    fee_cost: Decimal
    ts: int
    client_order_id: str | None = None
    meta: Dict[str, Any] | None = None


@runtime_checkable
class TradeRepository(Protocol):
    def insert(self, trade: Trade) -> None: ...
    def list_by_symbol(self, symbol: str, limit: int = 100) -> list[Trade]: ...


@runtime_checkable
class PositionRepository(Protocol):
    def get_open_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]: ...
    def upsert(self, position: Dict[str, Any]) -> None: ...


@runtime_checkable
class AuditRepository(Protocol):
    def record(self, event: Dict[str, Any]) -> None: ...


@runtime_checkable
class SnapshotRepository(Protocol):
    def upsert(self, snap: Dict[str, Any]) -> None: ...
    def get_last(self, symbol: str) -> Optional[Dict[str, Any]]: ...
