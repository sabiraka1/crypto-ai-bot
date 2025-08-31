# src/crypto_ai_bot/core/infrastructure/brokers/base.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class TickerDTO:
    symbol: str
    last: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    timestamp: int | None = None

@dataclass
class OrderDTO:
    id: str
    client_order_id: str
    symbol: str
    side: str  # "buy" | "sell"
    amount: Decimal
    status: str  # "open" | "closed" | "canceled" | ...
    filled: Decimal
    timestamp: int | None = None
    price: Decimal | None = None
    cost: Decimal | None = None
    fee_quote: Decimal = Decimal("0")  # ← НОВОЕ, комиссия в валюте котировки

class BalanceDTO:
    def __init__(self, *, free_quote: Decimal, free_base: Decimal) -> None:
        self.free_quote = free_quote
        self.free_base = free_base

class IBroker:
    async def fetch_ticker(self, symbol: str) -> TickerDTO: ...
    async def fetch_balance(self, symbol: str) -> BalanceDTO: ...
    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str) -> OrderDTO: ...
    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str) -> OrderDTO: ...
    async def fetch_open_orders(self, symbol: str): ...
