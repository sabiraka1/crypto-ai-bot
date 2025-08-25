from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Dict, Any

from .base import IBroker, TickerDTO, OrderDTO, BalanceDTO
from .ccxt_adapter import CcxtBroker


@dataclass
class LiveBroker(IBroker):
    """Тонкая обёртка над `CcxtBroker`. Оставлена для явного разделения режимов."""

    ccxt: CcxtBroker

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        return await self.ccxt.fetch_ticker(symbol)

    async def fetch_balance(self, symbol: str) -> BalanceDTO:
        return await self.ccxt.fetch_balance(symbol)

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Decimal, client_order_id: str) -> OrderDTO:
        return await self.ccxt.create_market_buy_quote(symbol=symbol, quote_amount=quote_amount, client_order_id=client_order_id)

    async def create_market_sell_base(self, *, symbol: str, base_amount: Decimal, client_order_id: str) -> OrderDTO:
        return await self.ccxt.create_market_sell_base(symbol=symbol, base_amount=base_amount, client_order_id=client_order_id)

    async def fetch_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return await self.ccxt.fetch_open_orders(symbol)