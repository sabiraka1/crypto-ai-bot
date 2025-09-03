from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class TickerDTO:
    last: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    symbol: str | None = None
    timestamp: int | None = None


class BaseBroker(ABC):
    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> TickerDTO: ...
    @abstractmethod
    async def fetch_balance(self, symbol: str) -> dict[str, Decimal]: ...
    @abstractmethod
    async def create_market_buy_quote(
        self, *, symbol: str, quote_amount: Decimal, client_order_id: str | None = None
    ) -> Any: ...
    @abstractmethod
    async def create_market_sell_base(
        self, *, symbol: str, base_amount: Decimal, client_order_id: str | None = None
    ) -> Any: ...
    @abstractmethod
    async def fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]: ...
