from __future__ import annotations
from typing import Protocol, Iterable, Optional, Dict, Any
from dataclasses import dataclass

class TradeRepositoryInterface(Protocol):
    def append(self, *, symbol: str, side: str, qty: float, price: float, fee: float,
               decision_id: Optional[str], order_id: Optional[str], client_order_id: Optional[str],
               ts_ms: int, note: Optional[str] = None) -> None: ...
    def last_closed_pnls(self, n: int) -> Iterable[float]: ...

class PositionRepositoryInterface(Protocol):
    def on_trade(self, *, symbol: str, side: str, qty: float, price: float, fee: float,
                 decision_id: Optional[str], order_id: Optional[str], ts_ms: int) -> None: ...
    def get_open(self) -> Iterable[Dict[str, Any]]: ...

class AuditRepositoryInterface(Protocol):
    def append(self, event: str, payload: Dict[str, Any]) -> None: ...

class IdempotencyRepositoryInterface(Protocol):
    def check_and_store(self, key: str, ttl_seconds: int) -> bool: ...
    def claim(self, key: str, ttl_seconds: int) -> bool: ...
    def commit(self, key: str) -> None: ...
    def release(self, key: str) -> None: ...

class DecisionsRepositoryInterface(Protocol):
    def put(self, decision: Dict[str, Any]) -> None: ...

@dataclass
class RepositoryInterfaces:
    trades: TradeRepositoryInterface
    positions: PositionRepositoryInterface
    audit: AuditRepositoryInterface
    idempotency: IdempotencyRepositoryInterface
    decisions: Optional[DecisionsRepositoryInterface] = None
