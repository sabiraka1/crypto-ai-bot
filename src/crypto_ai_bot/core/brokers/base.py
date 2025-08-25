from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Optional


@dataclass(frozen=True)
class TickerDTO:
    symbol: str
    last: Decimal
    bid: Decimal
    ask: Decimal
    timestamp: int


@dataclass(frozen=True)
class OrderDTO:
    id: str
    client_order_id: str
    symbol: str
    side: str                  # "buy" | "sell"
    amount: Decimal            # сколько покупаем/продаём (base или эквивалент — зависит от метода)
    status: str                # "open" | "closed" | "canceled" | "failed" | "partial"
    filled: Decimal            # сколько исполнено (в base)
    timestamp: int

    # ↓ чтобы не конфликтовать с backtest/бумагой и иметь больше контекста
    price: Optional[Decimal] = None   # средняя цена исполнения (если есть)
    cost: Optional[Decimal] = None    # суммарная стоимость (в quote), если известно
    remaining: Optional[Decimal] = None
    fee: Optional[Decimal] = None
    fee_currency: Optional[str] = None


@dataclass(frozen=True)
class BalanceDTO:
    """
    Нормализованный баланс под текущую пару:
    - free_quote / free_base — свободные средства для торговли
    - total_* опционально (если есть из источника)
    """
    free_quote: Decimal
    free_base:  Decimal
    total_quote: Optional[Decimal] = None
    total_base:  Optional[Decimal] = None


class IBroker(Protocol):
    async def fetch_ticker(self, symbol: str) -> TickerDTO: ...
    async def fetch_balance(self, symbol: str) -> BalanceDTO: ...

    async def create_market_buy_quote(
        self, *, symbol: str, quote_amount: Decimal, client_order_id: str
    ) -> OrderDTO: ...

    async def create_market_sell_base(
        self, *, symbol: str, base_amount: Decimal, client_order_id: str
    ) -> OrderDTO: ...
