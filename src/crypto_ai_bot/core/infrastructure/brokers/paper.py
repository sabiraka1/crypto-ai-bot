from __future__ import annotations

from typing import Any, Dict
from decimal import Decimal
from dataclasses import dataclass, field
import asyncio
from collections import defaultdict

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

_log = get_logger("brokers.paper")


@dataclass
class PaperBroker:
    """Симулятор брокера для paper trading."""
    
    exchange: str = "paper"
    settings: Any = None
    _balances: Dict[str, Decimal] = field(default_factory=lambda: {"USDT": dec("10000"), "BTC": dec("0.5")})
    _positions: Dict[str, Decimal] = field(default_factory=dict)
    _orders: Dict[str, Any] = field(default_factory=dict)
    _last_prices: Dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: dec("50000")))
    
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Возвращает фиктивный ticker."""
        price = self._last_prices[symbol]
        spread = price * dec("0.0002")  # 0.02% спред
        return {
            "symbol": symbol,
            "bid": str(price - spread),
            "ask": str(price + spread),
            "last": str(price),
            "timestamp": now_ms(),
        }
    
    async def fetch_balance(self, symbol: str = "") -> Dict[str, Any]:
        """Возвращает фиктивный баланс."""
        result = {}
        for asset, amount in self._balances.items():
            result[asset] = {
                "free": str(amount),
                "used": "0",
                "total": str(amount)
            }
        return result
    
    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 100) -> list[list]:
        """Возвращает фиктивные OHLCV данные."""
        price = float(self._last_prices[symbol])
        ohlcv = []
        ts = now_ms()
        
        for i in range(limit):
            # Симулируем небольшие колебания цены
            variation = 0.995 + (i % 10) * 0.001
            p = price * variation
            ohlcv.append([
                ts - (limit - i) * 60000,  # timestamp
                p * 0.999,  # open
                p * 1.001,  # high
                p * 0.998,  # low
                p,          # close
                100.0       # volume
            ])
        
        return ohlcv
    
    async def create_market_buy_quote(
        self, 
        symbol: str, 
        quote_amount: Decimal, 
        client_order_id: str | None = None
    ) -> Any:
        """Симулирует покупку."""
        price = self._last_prices[symbol]
        amount = quote_amount / price
        fee = quote_amount * dec("0.001")
        
        # Обновляем балансы
        base, quote = symbol.split("/")
        if quote in self._balances:
            self._balances[quote] -= (quote_amount + fee)
        if base in self._balances:
            self._balances[base] = self._balances.get(base, dec("0")) + amount
        
        order = {
            "id": f"paper_{client_order_id or now_ms()}",
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "side": "buy",
            "type": "market",
            "amount": str(amount),
            "filled": str(amount),
            "remaining": "0",
            "price": str(price),
            "cost": str(quote_amount),
            "fee": {"currency": quote, "cost": str(fee)},
            "fee_quote": str(fee),
            "status": "closed",
            "timestamp": now_ms(),
            "ts_ms": now_ms(),
        }
        
        if client_order_id:
            self._orders[client_order_id] = order
        
        return order
    
    async def create_market_sell_base(
        self,
        symbol: str,
        base_amount: Decimal,
        client_order_id: str | None = None
    ) -> Any:
        """Симулирует продажу."""
        price = self._last_prices[symbol]
        cost = base_amount * price
        fee = cost * dec("0.001")
        
        # Обновляем балансы
        base, quote = symbol.split("/")
        if base in self._balances:
            self._balances[base] -= base_amount
        if quote in self._balances:
            self._balances[quote] = self._balances.get(quote, dec("0")) + (cost - fee)
        
        order = {
            "id": f"paper_{client_order_id or now_ms()}",
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "side": "sell",
            "type": "market",
            "amount": str(base_amount),
            "filled": str(base_amount),
            "remaining": "0",
            "price": str(price),
            "cost": str(cost),
            "fee": {"currency": quote, "cost": str(fee)},
            "fee_quote": str(fee),
            "status": "closed",
            "timestamp": now_ms(),
            "ts_ms": now_ms(),
        }
        
        if client_order_id:
            self._orders[client_order_id] = order
        
        return order
    
    async def fetch_order(self, order_id: str, symbol: str) -> Any:
        """Получить ордер по ID."""
        return self._orders.get(order_id, {
            "id": order_id,
            "symbol": symbol,
            "status": "closed",
            "filled": "0",
            "remaining": "0",
        })
    
    async def fetch_open_orders(self, symbol: str | None = None) -> list[Any]:
        """В paper режиме все ордера сразу исполняются, поэтому открытых нет."""
        return []
    
    async def cancel_order(self, order_id: str, symbol: str) -> Any:
        """В paper режиме нечего отменять."""
        return {"id": order_id, "status": "canceled"}