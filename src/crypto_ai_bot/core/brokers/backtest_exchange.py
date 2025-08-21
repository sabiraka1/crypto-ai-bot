from __future__ import annotations
import time
import uuid
from typing import Any, Dict

from crypto_ai_bot.core.brokers.base import IBroker, TickerDTO, BalanceDTO, OrderDTO
from crypto_ai_bot.utils.logging import get_logger


class BacktestBroker(IBroker):
    """Простая paper-реализация: цены задаются через set_price(), баланс виртуальный.
    Подходит для быстрой интеграции и юнит-тестов use-case слоёв.
    """
    def __init__(self, settings: Any) -> None:
        self._log = get_logger("broker.backtest")
        self.settings = settings
        # начальные цены
        self._prices: Dict[str, float] = {s: 100.0 for s in (getattr(settings, "SYMBOLS", []) or ["BTC/USDT"])}
        # балансы: 10_000 quote по умолчанию + 0 base
        self._balances: Dict[str, float] = {"USDT": 10_000.0, "BTC": 0.0}

    # --- helpers ---
    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = float(price)

    def fetch_server_time_ms(self) -> int:
        return int(time.time() * 1000)

    # --- IBroker ---
    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        price = float(self._prices.get(symbol, 100.0))
        return TickerDTO(symbol=symbol, last=price, ts_ms=self.fetch_server_time_ms())

    async def fetch_balance(self) -> BalanceDTO:
        # Делим на free/total одинаково в простейшей модели
        free = dict(self._balances)
        total = dict(self._balances)
        return BalanceDTO(free=free, total=total)

    async def create_market_buy_quote(self, *, symbol: str, quote_amount: float, idempotency_key: str) -> OrderDTO:
        base, quote = symbol.split("/", 1)
        price = (await self.fetch_ticker(symbol)).last
        cost = float(quote_amount)
        base_qty = cost / max(price, 1e-12)
        # проверка средств
        if self._balances.get(quote, 0.0) + 1e-12 < cost:
            raise RuntimeError("Недостаточно средств quote для покупки")
        # исполнение
        self._balances[quote] = self._balances.get(quote, 0.0) - cost
        self._balances[base] = self._balances.get(base, 0.0) + base_qty
        oid = str(uuid.uuid4())
        return OrderDTO(
            id=oid,
            client_order_id=idempotency_key,  # для backtest можно вернуть сам ключ
            symbol=symbol,
            side="buy",
            type="market",
            amount=base_qty,
            price=price,
            status="closed",
        )

    async def create_market_sell_base(self, *, symbol: str, base_amount: float, idempotency_key: str) -> OrderDTO:
        base, quote = symbol.split("/", 1)
        price = (await self.fetch_ticker(symbol)).last
        qty = float(base_amount)
        if self._balances.get(base, 0.0) + 1e-12 < qty:
            raise RuntimeError("Недостаточно базовой валюты для продажи")
        proceeds = qty * price
        self._balances[base] = self._balances.get(base, 0.0) - qty
        self._balances[quote] = self._balances.get(quote, 0.0) + proceeds
        oid = str(uuid.uuid4())
        return OrderDTO(
            id=oid,
            client_order_id=idempotency_key,
            symbol=symbol,
            side="sell",
            type="market",
            amount=qty,
            price=price,
            status="closed",
        )
