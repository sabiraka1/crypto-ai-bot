from __future__ import annotations

from typing import Any, Dict, List, Literal
from decimal import Decimal
from dataclasses import dataclass
from collections import defaultdict

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.time import now_ms

# Порт: только импорт (контракт), реализация — ниже в адаптере
from crypto_ai_bot.core.application.ports import BrokerPort

_log = get_logger("brokers.paper")


@dataclass
class PaperBroker:
    """Симулятор брокера для paper trading."""
    settings: Any

    def __post_init__(self) -> None:
        # Инициализируем атрибуты после создания (оставлено как есть)
        self._balances: Dict[str, Decimal] = {"USDT": dec("10000"), "BTC": dec("0.5")}
        self._positions: Dict[str, Decimal] = {}
        self._orders: Dict[str, Any] = {}
        self._last_prices: Dict[str, Decimal] = defaultdict(lambda: dec("50000"))
        self.exchange = getattr(self.settings, "EXCHANGE", "paper") if self.settings else "paper"

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
            result[asset] = {"free": str(amount), "used": "0", "total": str(amount)}
        return result

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 100) -> List[List[float]]:
        """Возвращает фиктивные OHLCV данные."""
        price = float(self._last_prices[symbol])
        ohlcv: List[List[float]] = []
        ts = now_ms()
        for i in range(limit):
            # Симулируем небольшие колебания цены
            variation = 0.995 + (i % 10) * 0.001
            p = price * variation
            ohlcv.append([
                float(ts - (limit - i) * 60000),  # timestamp
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
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        """Симулирует покупку (как было)."""
        price = self._last_prices[symbol]
        amount = quote_amount / price
        fee = quote_amount * dec("0.001")

        # Обновляем балансы
        base, quote = symbol.split("/")
        if quote in self._balances:
            self._balances[quote] -= (quote_amount + fee)
        if base not in self._balances:
            self._balances[base] = dec("0")
        self._balances[base] = self._balances[base] + amount

        order = {
            "id": f"paper_{client_order_id or now_ms()}",
            "clientOrderId": client_order_id,
            "client_order_id": client_order_id,  # для совместимости
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
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        """Симулирует продажу (как было)."""
        price = self._last_prices[symbol]
        cost = base_amount * price
        fee = cost * dec("0.001")

        # Обновляем балансы
        base, quote = symbol.split("/")
        if base in self._balances:
            self._balances[base] -= base_amount
        if quote not in self._balances:
            self._balances[quote] = dec("0")
        self._balances[quote] = self._balances[quote] + (cost - fee)

        order = {
            "id": f"paper_{client_order_id or now_ms()}",
            "clientOrderId": client_order_id,
            "client_order_id": client_order_id,  # для совместимости
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

    async def fetch_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Получить ордер по ID."""
        default_order: Dict[str, Any] = {
            "id": order_id,
            "symbol": symbol,
            "status": "closed",
            "filled": "0",
            "remaining": "0",
        }
        result: Dict[str, Any] = self._orders.get(order_id, default_order)
        return result

    async def fetch_open_orders(self, symbol: str | None = None) -> List[Dict[str, Any]]:
        """В paper режиме все ордера сразу исполняются, поэтому открытых нет."""
        return []

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """В paper режиме нечего отменять."""
        return {"id": order_id, "status": "canceled"}


# -------------------------------
# ТОНКИЙ ПОРТ-АДАПТЕР (без смены логики)
# -------------------------------
class PaperBrokerPortAdapter(BrokerPort):
    """
    Реализация BrokerPort поверх текущего PaperBroker.
    Ничего в логике не меняем — только «переводим» вызовы в существующие методы.
    """

    def __init__(self, core: PaperBroker) -> None:
        self._core = core

    async def place_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quote_amount: Decimal,
        *,
        time_in_force: str = "GTC",
        idempotency_key: str | None = None,
    ) -> Dict[str, Any]:
        # BUY: есть прямой метод «покупка на сумму quote»
        if side == "buy":
            return await self._core.create_market_buy_quote(
                symbol=symbol,
                quote_amount=quote_amount,
                client_order_id=idempotency_key,
            )
        # SELL: у core метод «продажа base». Пересчитываем base = quote/price (по текущей last).
        # Это ровно та же формула, что уже используется в create_market_buy_quote.
        ticker = await self._core.fetch_ticker(symbol)
        price = dec(ticker["last"])
        if price <= 0:
            raise ValueError("Invalid price from ticker for sell")
        base_amount = (quote_amount / price)
        return await self._core.create_market_sell_base(
            symbol=symbol,
            base_amount=base_amount,
            client_order_id=idempotency_key,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return await self._core.cancel_order(order_id=order_id, symbol=symbol)

    async def fetch_open_orders(self, symbol: str | None = None) -> List[Dict[str, Any]]:
        return await self._core.fetch_open_orders(symbol)

    async def fetch_order(self, symbol: str, order_id: str) -> Dict[str, Any] | None:
        return await self._core.fetch_order(order_id=order_id, symbol=symbol)

    async def get_balance(self) -> Dict[str, Any]:
        return await self._core.fetch_balance()
