from __future__ import annotations

from typing import Any, Dict
from decimal import Decimal
from dataclasses import dataclass

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("brokers.paper")


@dataclass
class PaperBroker:
    """Симулятор брокера для paper trading."""
    
    settings: Any
    
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Возвращает фиктивный ticker."""
        return {
            "symbol": symbol,
            "bid": "50000.00",
            "ask": "50010.00",
            "last": "50005.00",
        }
    
    async def fetch_balance(self, symbol: str = "") -> Dict[str, Any]:
        """Возвращает фиктивный баланс."""
        return {
            "USDT": {"free": "10000.00", "total": "10000.00"},
            "BTC": {"free": "0.5", "total": "0.5"},
        }
    
    async def create_market_buy_quote(
        self, 
        symbol: str, 
        quote_amount: Decimal, 
        client_order_id: str | None = None
    ) -> Any:
        """Симулирует покупку."""
        price = dec("50000")
        amount = quote_amount / price
        return {
            "id": f"paper_{client_order_id or 'order'}",
            "symbol": symbol,
            "side": "buy",
            "amount": str(amount),
            "price": str(price),
            "cost": str(quote_amount),
            "fee_quote": str(quote_amount * dec("0.001")),
        }
    
    async def create_market_sell_base(
        self,
        symbol: str,
        base_amount: Decimal,
        client_order_id: str | None = None
    ) -> Any:
        """Симулирует продажу."""
        price = dec("50000")
        cost = base_amount * price
        return {
            "id": f"paper_{client_order_id or 'order'}",
            "symbol": symbol,
            "side": "sell",
            "amount": str(base_amount),
            "price": str(price),
            "cost": str(cost),
            "fee_quote": str(cost * dec("0.001")),
        }