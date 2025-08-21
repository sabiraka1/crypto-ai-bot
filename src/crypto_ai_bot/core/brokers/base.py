## `base.py`
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Protocol, Optional
@dataclass(frozen=True)
class TickerDTO:
    symbol: str
    last: Decimal
    bid: Decimal
    ask: Decimal
    timestamp: int  # ms
@dataclass(frozen=True)
class BalanceDTO:
    free: Dict[str, Decimal]
    used: Dict[str, Decimal]
    total: Dict[str, Decimal]
    timestamp: int  # ms
@dataclass(frozen=True)
class OrderDTO:
    id: str
    client_order_id: str
    symbol: str
    side: str  # 'buy' | 'sell'
    amount: Decimal  # base amount for SELL; computed base amount for BUY
    status: str  # 'open' | 'closed' | 'failed'
    filled: Decimal  # base amount filled
    price: Decimal  # average execution price
    cost: Decimal  # quote cost (BUY spent, SELL received)
    timestamp: int  # ms
class IBroker(Protocol):
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        ...
    async def fetch_balance(self) -> BalanceDTO:
        ...
    async def create_market_buy_quote(self, symbol: str, quote_amount: Decimal, *, client_order_id: str) -> OrderDTO:
        """Market BUY for a quote amount (e.g., spend USDT). Returns filled base amount."""
        ...
    async def create_market_sell_base(self, symbol: str, base_amount: Decimal, *, client_order_id: str) -> OrderDTO:
        """Market SELL for a base amount (e.g., sell BTC)."""