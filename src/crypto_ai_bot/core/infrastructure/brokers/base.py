"""
Base broker implementation.
Абстрактный базовый класс для всех брокеров (live, paper, etc).
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Optional

from crypto_ai_bot.core.application.ports import (
    BrokerPort,
    OrderSide,
    OrderDTO,
    PositionDTO,
    BalanceDTO,
    TickerDTO,
)
from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.trace import get_trace_id


class BaseBroker(ABC, BrokerPort):
    """
    Базовый класс для всех брокеров.
    Реализует общую логику и валидацию.
    """

    def __init__(
        self,
        exchange: str,
        mode: str,
        rate_limit_rps: float = 10.0,
        rate_limit_burst: int = 20,
    ):
        """
        Args:
            exchange: Название биржи (gateio, binance, etc)
            mode: Режим работы (live, paper)
            rate_limit_rps: Requests per second лимит
            rate_limit_burst: Максимальный burst размер
        """
        self.exchange = exchange
        self.mode = mode
        self.rate_limit_rps = rate_limit_rps
        self.rate_limit_burst = rate_limit_burst

        # Для rate limiting (simple token bucket)
        self._tokens = float(rate_limit_burst)
        self._last_refill_mono = time.monotonic()

        # Кэш последних тикеров (для оптимизации)
        # (ticker, cached_mono_timestamp)
        self._ticker_cache: dict[str, tuple[TickerDTO, float]] = {}
        self._ticker_cache_ttl = 1.0  # секунды

    # ============= RATE LIMITING =============

    async def _check_rate_limit(self) -> None:
        """Проверка rate limit перед запросом (monotonic)"""
        now_mono = time.monotonic()
        time_passed = now_mono - self._last_refill_mono

        # Пополняем токены
        self._tokens = min(
            self.rate_limit_burst,
            self._tokens + time_passed * self.rate_limit_rps,
        )
        self._last_refill_mono = now_mono

        # Ждем если токенов нет
        if self._tokens < 1:
            # защита от отрицательной паузы
            missing = max(0.0, 1.0 - self._tokens)
            wait_time = missing / max(1e-9, self.rate_limit_rps)
            await asyncio.sleep(wait_time)
            self._tokens = 1.0

        self._tokens -= 1.0

    # ============= ВАЛИДАЦИЯ =============

    def _validate_symbol(self, symbol: str) -> None:
        """Валидация торговой пары"""
        if not symbol or "/" not in symbol:
            raise ValueError(f"Invalid symbol format: {symbol}")

    def _validate_amount(self, amount: Decimal) -> None:
        """Валидация количества"""
        if amount <= 0:
            raise ValueError(f"Amount must be positive: {amount}")

    def _validate_price(self, price: Decimal) -> None:
        """Валидация цены"""
        if price <= 0:
            raise ValueError(f"Price must be positive: {price}")

    def _validate_client_order_id(self, client_order_id: str) -> None:
        """Валидация client order ID"""
        if not client_order_id:
            raise ValueError("client_order_id is required")
        if len(client_order_id) > 64:
            raise ValueError(f"client_order_id too long: {client_order_id}")

    # ============= MARKET DATA =============

    async def fetch_ticker(self, symbol: str) -> TickerDTO:
        """
        Получить текущие цены с кэшированием.
        """
        self._validate_symbol(symbol)

        # Проверяем кэш
        cached = self._ticker_cache.get(symbol)
        if cached:
            ticker, ts_mono = cached
            age = time.monotonic() - ts_mono
            if age < self._ticker_cache_ttl:
                return ticker

        # Rate limit
        await self._check_rate_limit()

        # Получаем свежие данные
        ticker = await self._fetch_ticker_impl(symbol)

        # Сохраняем в кэш
        self._ticker_cache[symbol] = (ticker, time.monotonic())

        return ticker

    @abstractmethod
    async def _fetch_ticker_impl(self, symbol: str) -> TickerDTO:
        """Реализация получения тикера (переопределить в наследниках)"""
        ...

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        """
        Получить OHLCV свечи.
        """
        self._validate_symbol(symbol)

        if limit <= 0 or limit > 1000:
            raise ValueError(f"Invalid limit: {limit}")

        valid_timeframes = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
        if timeframe not in valid_timeframes:
            raise ValueError(f"Invalid timeframe: {timeframe}")

        await self._check_rate_limit()
        return await self._fetch_ohlcv_impl(symbol, timeframe, limit)

    @abstractmethod
    async def _fetch_ohlcv_impl(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]]:
        """Реализация получения OHLCV (переопределить в наследниках)"""
        ...

    # ============= ACCOUNT =============

    async def fetch_balance(self) -> dict[str, BalanceDTO]:
        """Получить балансы счета"""
        await self._check_rate_limit()
        return await self._fetch_balance_impl()

    @abstractmethod
    async def _fetch_balance_impl(self) -> dict[str, BalanceDTO]:
        """Реализация получения баланса (переопределить в наследниках)"""
        ...

    async def fetch_position(self, symbol: str) -> Optional[PositionDTO]:
        """Получить открытую позицию"""
        self._validate_symbol(symbol)
        await self._check_rate_limit()
        return await self._fetch_position_impl(symbol)

    @abstractmethod
    async def _fetch_position_impl(self, symbol: str) -> Optional[PositionDTO]:
        """Реализация получения позиции (переопределить в наследниках)"""
        ...

    # ============= ORDERS =============

    async def create_market_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        client_order_id: str,
    ) -> OrderDTO:
        """Создать рыночный ордер"""
        self._validate_symbol(symbol)
        self._validate_amount(amount)
        self._validate_client_order_id(client_order_id)

        await self._check_rate_limit()

        trace_id = get_trace_id()  # Optional[str]
        return await self._create_market_order_impl(
            symbol, side, amount, client_order_id, trace_id
        )

    @abstractmethod
    async def _create_market_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        client_order_id: str,
        trace_id: Optional[str],
    ) -> OrderDTO:
        """Реализация создания рыночного ордера"""
        ...

    async def create_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        client_order_id: str,
    ) -> OrderDTO:
        """Создать лимитный ордер"""
        self._validate_symbol(symbol)
        self._validate_amount(amount)
        self._validate_price(price)
        self._validate_client_order_id(client_order_id)

        await self._check_rate_limit()

        trace_id = get_trace_id()
        return await self._create_limit_order_impl(
            symbol, side, amount, price, client_order_id, trace_id
        )

    @abstractmethod
    async def _create_limit_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        client_order_id: str,
        trace_id: Optional[str],
    ) -> OrderDTO:
        """Реализация создания лимитного ордера"""
        ...

    async def create_stop_loss_order(
        self,
        symbol: str,
        amount: Decimal,
        stop_price: Decimal,
        client_order_id: str,
    ) -> OrderDTO:
        """Создать стоп-лосс ордер"""
        self._validate_symbol(symbol)
        self._validate_amount(amount)
        self._validate_price(stop_price)
        self._validate_client_order_id(client_order_id)

        await self._check_rate_limit()

        trace_id = get_trace_id()
        return await self._create_stop_loss_order_impl(
            symbol, amount, stop_price, client_order_id, trace_id
        )

    @abstractmethod
    async def _create_stop_loss_order_impl(
        self,
        symbol: str,
        amount: Decimal,
        stop_price: Decimal,
        client_order_id: str,
        trace_id: Optional[str],
    ) -> OrderDTO:
        """Реализация создания стоп-лосс ордера"""
        ...

    async def cancel_order(self, order_id: str, symbol: str) -> OrderDTO:
        """Отменить ордер"""
        if not order_id:
            raise ValueError("order_id is required")
        self._validate_symbol(symbol)

        await self._check_rate_limit()
        return await self._cancel_order_impl(order_id, symbol)

    @abstractmethod
    async def _cancel_order_impl(self, order_id: str, symbol: str) -> OrderDTO:
        """Реализация отмены ордера"""
        ...

    async def fetch_order(self, order_id: str, symbol: str) -> OrderDTO:
        """Получить информацию об ордере"""
        if not order_id:
            raise ValueError("order_id is required")
        self._validate_symbol(symbol)

        await self._check_rate_limit()
        return await self._fetch_order_impl(order_id, symbol)

    @abstractmethod
    async def _fetch_order_impl(self, order_id: str, symbol: str) -> OrderDTO:
        """Реализация получения ордера"""
        ...

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> list[OrderDTO]:
        """Получить открытые ордера"""
        if symbol:
            self._validate_symbol(symbol)

        await self._check_rate_limit()
        return await self._fetch_open_orders_impl(symbol)

    @abstractmethod
    async def _fetch_open_orders_impl(self, symbol: Optional[str]) -> list[OrderDTO]:
        """Реализация получения открытых ордеров"""
        ...

    async def fetch_closed_orders(
        self,
        symbol: str,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[OrderDTO]:
        """Получить закрытые ордера"""
        self._validate_symbol(symbol)

        if limit <= 0 or limit > 500:
            raise ValueError(f"Invalid limit: {limit}")

        await self._check_rate_limit()
        return await self._fetch_closed_orders_impl(symbol, since, limit)

    @abstractmethod
    async def _fetch_closed_orders_impl(
        self,
        symbol: str,
        since: Optional[datetime],
        limit: int,
    ) -> list[OrderDTO]:
        """Реализация получения закрытых ордеров"""
        ...

    # ============= HELPERS =============

    def calculate_spread_pct(self, bid: Decimal, ask: Decimal) -> Decimal:
        """Рассчитать спред в процентах"""
        if bid <= 0 or ask <= 0:
            return dec("0")

        mid = (bid + ask) / 2
        if mid == 0:
            return dec("0")

        spread = ask - bid
        return (spread / mid) * 100

    def normalize_symbol(self, symbol: str) -> str:
        """
        Нормализовать формат символа для биржи.
        BTC/USDT -> BTC_USDT (для Gate.io)
        """
        # Переопределить в наследниках если нужен другой формат
        return symbol.replace("/", "_")

    def denormalize_symbol(self, exchange_symbol: str) -> str:
        """
        Обратное преобразование символа.
        BTC_USDT -> BTC/USDT
        """
        # Переопределить в наследниках если нужен другой формат
        return exchange_symbol.replace("_", "/")
