from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, List, Dict, Any, Optional


@dataclass(frozen=True)
class TickerDTO:
    symbol: str
    last: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    timestamp: Optional[int] = None


@dataclass(frozen=True)
class BalanceDTO:
    free_quote: Decimal
    free_base: Decimal


@dataclass(frozen=True)
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


class IBroker(Protocol):
    async def fetch_ticker(self, symbol: str) -> TickerDTO: ...
    async def fetch_balance(self, symbol: str) -> BalanceDTO: ...
    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str) -> OrderDTO: ...
    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str) -> OrderDTO: ...

    # опционально для сверок
    async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:  # noqa: D401
        """Возвращает открытые ордера по символу, если поддерживается брокером."""
        return []
