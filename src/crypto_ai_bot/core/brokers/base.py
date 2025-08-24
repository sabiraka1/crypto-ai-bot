from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Optional


class IBroker(Protocol):
    async def fetch_ticker(self, symbol: str) -> "TickerDTO": ...
    async def fetch_balance(self) -> "BalanceDTO": ...
    async def create_market_buy_quote(self, *, symbol: str, amount_quote: Decimal) -> "OrderDTO": ...
    async def create_market_sell_base(self, *, symbol: str, amount_base: Decimal) -> "OrderDTO": ...


@dataclass(frozen=True)
class TickerDTO:
    symbol: str
    last: Decimal
    bid: Decimal
    ask: Decimal
    timestamp: int


@dataclass(frozen=True)
class BalanceDTO:
    free_quote: Decimal
    free_base: Decimal
    timestamp: int
    # при необходимости можно расширить позже


@dataclass(frozen=True)
class OrderDTO:
    id: str
    client_order_id: str
    symbol: str
    side: str                   # 'buy' | 'sell'
    amount: Decimal             # запрошенный объём (base для sell, quote-деньги для buy? зависит от метода)
    status: str                 # 'open' | 'partial' | 'closed' | 'failed'
    filled: Decimal             # фактически исполнено (в base, если sell; для buy — исполненный base, если брокер так отдаёт)
    timestamp: int

    # --- новые поля (опциональны) ---
    remaining: Decimal = Decimal("0")       # сколько ещё не исполнено в base
    fee: Decimal = Decimal("0")             # суммарная комиссия
    fee_currency: str = ""                  # валюта комиссии (например, "USDT")
