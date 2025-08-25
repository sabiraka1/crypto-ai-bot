from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class TickerDTO:
    symbol: str
    last: Decimal
    bid: Decimal
    ask: Decimal
    timestamp: int


@dataclass
class BalanceDTO:
    free_quote: Decimal
    free_base: Decimal


@dataclass
class OrderDTO:
    id: str
    client_order_id: str
    symbol: str
    side: str
    amount: Decimal
    status: str
    filled: Decimal
    timestamp: int
    price: Optional[Decimal] = None
    cost: Optional[Decimal] = None
    fee_cost: Optional[Decimal] = None
    fee_currency: Optional[str] = None


class IBroker(ABC):
    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> TickerDTO: ...

    @abstractmethod
    async def fetch_balance(self, symbol: str) -> BalanceDTO: ...

    @abstractmethod
    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str) -> OrderDTO: ...

    @abstractmethod
    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str) -> OrderDTO: ...