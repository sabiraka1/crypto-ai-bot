from __future__ import annotations

from typing import Protocol, runtime_checkable, Any, Dict, List, Optional
from decimal import Decimal

# Re-export domain models expected by some tests
try:
    # Trade/Position live in core.types.trading — делаем реэкспорт для совместимости старых тестов
    from crypto_ai_bot.core.types.trading import Trade as Trade  # type: ignore
except Exception:  # pragma: no cover - если типов нет, тесты упадут раньше по другой причине
    Trade = Any  # fallback


@runtime_checkable
class UnitOfWork(Protocol):
    def __enter__(self) -> Any: ...
    def __exit__(self, exc_type, exc, tb) -> None: ...


@runtime_checkable
class PositionRepository(Protocol):
    def upsert(self, position: Dict[str, Any]) -> None: ...
    def get_open(self) -> List[Dict[str, Any]]: ...
    def get_by_id(self, pos_id: str) -> Optional[Dict[str, Any]]: ...
    def close(self, pos_id: str) -> None: ...


@runtime_checkable
class TradeRepository(Protocol):
    def insert(self, trade: Dict[str, Any]) -> None: ...
    def list_by_symbol(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]: ...


@runtime_checkable
class AuditRepository(Protocol):
    def append(self, record: Dict[str, Any]) -> None: ...


@runtime_checkable
class IdempotencyRepository(Protocol):
    """
    Контракт идемпотентности.
    """
    def claim(self, key: str, payload: Dict[str, Any], ttl_seconds: int) -> bool: ...
    def commit(self, key: str, result: Dict[str, Any]) -> None: ...
    def release(self, key: str) -> None: ...
    def get_original(self, key: str) -> Optional[Dict[str, Any]]: ...
