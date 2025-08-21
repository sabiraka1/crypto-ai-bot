from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TickerDTO:
    """DTO тикера рынка (минимально необходимое)."""
    symbol: str
    last: float  # последняя цена
    ts_ms: int | None = None


@dataclass(slots=True)
class BalanceDTO:
    """DTO баланса. Совместимо с проверкой: balance['free'][base] < qty."""
    free: dict[str, float]
    total: dict[str, float]


@dataclass(slots=True)
class OrderDTO:
    """DTO ордера/сделки (результат размещения)."""
    id: str
    client_order_id: str
    symbol: str
    side: str        # "buy" | "sell"
    type: str        # "market" | "limit" | ...
    amount: float    # кол-во базовой валюты
    price: float     # средняя/исполненная цена
    status: str      # "open" | "closed" | "canceled"


class IBroker(Protocol):
    """Контракт брокера/биржи (асинхронный)."""

    async def fetch_ticker(self, symbol: str) -> TickerDTO: ...

    async def fetch_balance(self) -> BalanceDTO: ...

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: float, idempotency_key: str) -> OrderDTO: ...

    async def create_market_sell_base(self, *, symbol: str, base_amount: float, idempotency_key: str) -> OrderDTO: ...